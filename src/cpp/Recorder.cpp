#include "Recorder.h"
#include "Log.h"

#include <thread>
#include <mutex>
#include <condition_variable>


#include <dv-processing/core/core.hpp>
#include <dv-processing/core/stereo_event_stream_slicer.hpp>
#include <dv-processing/io/camera/discovery.hpp>
#include <dv-processing/io/camera/sync_camera_input_base.hpp>
#include <dv-processing/io/stereo_camera_writer.hpp>
#include <dv-processing/visualization/event_visualizer.hpp>
#include <dv-processing/io/stereo_camera_recording.hpp>
#include <dv-processing/io/data_read_handler.hpp>

#include <opencv2/highgui.hpp>

namespace StereoRecorder
{

	struct StereoBatch {
		std::shared_ptr<const dv::EventStore> left;
		std::shared_ptr<const dv::EventStore> right;
	};

	int record(const std::filesystem::path &rawDir, bool showVisualization, std::atomic<bool>& stopSignal)
	{

		const auto cameras = dv::io::camera::discover();

		const size_t num_cameras = cameras.size();
		
		if(num_cameras != 2)
			throw dv::exceptions::RuntimeError("Unable to discover two cameras");

		Log::info("Found ", num_cameras, " cameras!");

		
		Log::info("Camera ", 0, ": ", cameras[0].cameraModel, "_", cameras[0].serialNumber);
		Log::info("Camera ", 1, ": ", cameras[1].cameraModel, "_", cameras[1].serialNumber);
		
		auto leftCamera = dv::io::camera::openSync(cameras[0]);
		auto rightCamera = dv::io::camera::openSync(cameras[1]);

		dv::io::camera::synchronizeAnyTwo(leftCamera, rightCamera);

		if(leftCamera->isMaster())
			Log::info("The left camera is clock syncronization master");
		else if (rightCamera->isMaster())	
			Log::info("The right camera is clock syncronization master");
		else
			throw dv::exceptions::RuntimeError("No clock syncronization master was detected");


		// temporal, change to consistent load function
		std::filesystem::path camMetaFilePath = rawDir / "camera_metadata.txt";
		std::ofstream camMetadataStream(camMetaFilePath);

		camMetadataStream << "Do not change or remove this file!\n";
		
		camMetadataStream << leftCamera->getCameraName();
		camMetadataStream << "\n";
		if (leftCamera->getEventResolution().has_value())
		{
			auto resolution = leftCamera->getEventResolution();
			camMetadataStream << resolution->width << " " << resolution->height;
		}

		camMetadataStream << "\n";


		camMetadataStream << rightCamera->getCameraName();
		camMetadataStream << "\n";
		if (rightCamera->getEventResolution().has_value())
		{
			auto resolution = rightCamera->getEventResolution();
			camMetadataStream << resolution->width << " " << resolution->height;
		}
		
		camMetadataStream.close();

		// readonly to make clear that the file contents are not meant to change	
		std::filesystem::permissions(
			camMetaFilePath, 
			std::filesystem::perms::owner_write | 
			std::filesystem::perms::group_write |
			std::filesystem::perms::others_write,
			std::filesystem::perm_options::remove
		);

		std::filesystem::path out = rawDir / "stereo_recording.aedat4";
		dv::io::StereoCameraWriter writer(out.string(), *leftCamera, *rightCamera);

		std::mutex queueMutex;
		std::condition_variable visQueueCondition;
		std::deque<std::shared_ptr<const dv::EventStore>> leftQueue;
		std::deque<std::shared_ptr<const dv::EventStore>> rightQueue;
		const size_t MAX_QUEUE_SIZE = 5;
		size_t droppedVisFrames = 0;

		// Example for usage of the DataReadHandler Class:
		// https://gitlab.com/inivation/dv/dv-processing/-/blob/master/samples/io/stereo-live-writer/stereo-live-writer.cpp#L26
		dv::io::DataReadHandler leftHandler, rightHandler;

		// TODO: ADD IMU for Kalibr

		leftHandler.mEventHandler = [&](const dv::EventStore &events) 
		{
			// Priority 1: write events
			writer.left.writeEvents(events);	

			// Priority 2: send events to visualization thread 
			if (showVisualization)
			{
				auto leftEventPtr = std::make_shared<dv::EventStore>(events);		
				{
					std::scoped_lock<std::mutex> lock(queueMutex);
					
					if (leftQueue.size() >= MAX_QUEUE_SIZE)
					{
						droppedVisFrames++;
						leftQueue.pop_front();
					}
					leftQueue.push_back(std::move(leftEventPtr));
				}
				visQueueCondition.notify_one();
			}
		};
		rightHandler.mEventHandler = [&](const dv::EventStore &events) 
		{
			writer.right.writeEvents(events);	

			if (showVisualization)
			{
				auto rightEventPtr = std::make_shared<dv::EventStore>(events);		
				{
					std::scoped_lock<std::mutex> lock(queueMutex);
					
					if (rightQueue.size() >= MAX_QUEUE_SIZE)
					{
						droppedVisFrames++;
						rightQueue.pop_front();
					}
					rightQueue.push_back(std::move(rightEventPtr));
				}
				visQueueCondition.notify_one();
			}
		};


		// recording (producer) thread
		std::thread recordingThread([&]() {
			Log::info("Starting the recording!");
			while (!stopSignal.load() && leftCamera->isRunning() && rightCamera->isRunning())
			{
				if (!leftCamera->handleNext(leftHandler)) break;
				if (!rightCamera->handleNext(rightHandler)) break;
			}
			visQueueCondition.notify_all();
			Log::info("Recording Thread Finished");
		});

		// visualization loop (main thread)
		if (showVisualization)
		{
			dv::StereoEventStreamSlicer slicer;
			dv::visualization::EventVisualizer leftVis(leftCamera->getEventResolution().value());
			dv::visualization::EventVisualizer rightVis(rightCamera->getEventResolution().value());

			cv::namedWindow("Left", cv::WINDOW_NORMAL);
			cv::namedWindow("Right", cv::WINDOW_NORMAL);

			// https://gitlab.com/inivation/dv/dv-processing/-/blob/master/samples/io/stereo-capture/stereo-capture.cpp
			slicer.doEveryNumberOfEvents(15000,
				// Here we receive events from two camera, time-synchronized
				[&](const dv::EventStore &leftEvents, const dv::EventStore &rightEvents) {
					if (showVisualization)
					{
						// Perform visualization and show preview
						cv::imshow("Left", leftVis.generateImage(leftEvents));
						cv::imshow("Right", rightVis.generateImage(rightEvents));

						// Signal exit if ESC or "q" key is pressed
						char key = (char) cv::waitKey(1);
						if (key == 27 || key == 'q'){
							stopSignal.store(true);
						}
					}
			});

			// consumer
			while(!stopSignal.load()) {
				StereoBatch batch;
				// use unique lock instead of scoped lock for dynamic locking and
				{
					std::unique_lock<std::mutex> lock(queueMutex);

					visQueueCondition.wait_for(lock, std::chrono::milliseconds(50), [&]{
						// wait until we have stop signal or full stereo pair
						return stopSignal.load() || (!leftQueue.empty() && !rightQueue.empty());
					});

					if (stopSignal.load()) break;

					if (!leftQueue.empty() && !rightQueue.empty()) 
					{
						batch.left = leftQueue.front(); leftQueue.pop_front();
						batch.right = rightQueue.front(); rightQueue.pop_front();
						// latest is now {nullptr, nullptr}, ready for new data
					}
					// unlock here so that the producer thread can push new data
					// while slicer is processing
				}
				if (batch.left && batch.right)
					slicer.accept(*batch.left, *batch.right);
				else 
					cv::waitKey(1); 
			}
			
			if (showVisualization) {
				Log::info("Visualization frames dropped: ", droppedVisFrames);
			}
			cv::destroyAllWindows();
		}
		// When no visualization, the thread joins below will block until recording completes

		// Ensure worker thread stops
		stopSignal.store(true);
		visQueueCondition.notify_all();
		
		if (recordingThread.joinable())
			recordingThread.join();

		return EXIT_SUCCESS;

	}
}
