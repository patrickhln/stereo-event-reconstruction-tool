#include <atomic>
#include <condition_variable>
#include <csignal>
#include <cstdlib>
#include <string>
#include <filesystem>

#include <thread>
#include <mutex>

#include <dv-processing/core/core.hpp>
#include <dv-processing/core/stereo_event_stream_slicer.hpp>
#include <dv-processing/io/camera/discovery.hpp>
#include <dv-processing/io/camera/sync_camera_input_base.hpp>
#include <dv-processing/io/stereo_camera_writer.hpp>
#include <dv-processing/visualization/event_visualizer.hpp>
#include <dv-processing/io/stereo_camera_recording.hpp>

#include <opencv2/highgui.hpp>
#include "Log.h"

void logUsage(char* argv[]);

static std::atomic<bool> stopSignalDetection(false);

static void signalHandler(int)
{
	stopSignalDetection.store(true);
}

struct StereoBatch {
    std::shared_ptr<const dv::EventStore> left;
    std::shared_ptr<const dv::EventStore> right;
};

int record(const std::filesystem::path &path, bool showVisualization)
{

	std::signal(SIGINT, signalHandler);
	std::signal(SIGTERM, signalHandler);
	
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
	std::filesystem::path camMetaFilePath = path / "camera_metadata.txt";
	std::ofstream camMetadataStream(camMetaFilePath);

	camMetadataStream << "Do not change or remove this file!";
	
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

	std::filesystem::path out = path / "stereo_recording.aedat4";
	dv::io::StereoCameraWriter writer(out.string(), *leftCamera, *rightCamera);

	std::mutex queueMutex;
	std::condition_variable visQueueCondition;

	StereoBatch latest;
	bool hasLatest = false;
	// std::atomic allows thread-safe reads/writes without a mutex.
	// Multiple threads can safely increment this counter simultaneously.
	std::atomic<uint64_t> droppedVisFrames{0};

	// producer thread (worker)
	std::thread recordingThread([&]() {

		Log::info("Starting the recording!");	
		while (!stopSignalDetection.load() && leftCamera->isRunning() && rightCamera->isRunning())
		{
			// For each of the available streams try readin a packet and write
			// immediately to a file	
			if (leftCamera->isEventStreamAvailable() && rightCamera->isEventStreamAvailable())
			{
				// consider add logto this worker ever ~10seconds to keep track of dropped frames etc
				auto leftEvents = leftCamera->getNextEventBatch();
				auto rightEvents = rightCamera->getNextEventBatch();

				if (leftEvents.has_value() && rightEvents.has_value())
				{
					// Write directly to file first (highest priority)
					writer.left.writeEvents(*leftEvents); 
					writer.right.writeEvents(*rightEvents);

					// producer: update visualization queue
					if (showVisualization) 
					{
						// Create shared_ptr outside lock to minimize critical section
						auto lPtr = std::make_shared<dv::EventStore>(std::move(*leftEvents)); 
						auto rPtr = std::make_shared<dv::EventStore>(std::move(*rightEvents));

						{
							std::scoped_lock<std::mutex> lock(queueMutex);
							if (hasLatest) {
								// fetch_add atomically adds 1 and returns old value (like counter++)
								// memory_order_relaxed = fastest option, no synchronization guarantees
								// with other variables. Fine here since we only care about the count.
								droppedVisFrames.fetch_add(1, std::memory_order_relaxed);
							}
							latest = {std::move(lPtr), std::move(rPtr)};
							hasLatest = true;
						}
						// notify the consumer thread that new data is available
						visQueueCondition.notify_one();
					}
				}
				else
				{
					// No events available, yield CPU briefly
					// alternative: std::this_thread::sleep_for(1ms);
					std::this_thread::yield();
				}
			} else 
			{
            	// If we didn't do work this cycle, sleep briefly to yield CPU.
	        	std::this_thread::sleep_for(std::chrono::milliseconds(1));
			}
			if (leftCamera->isFrameStreamAvailable() && rightCamera->isFrameStreamAvailable())
			{
				const auto &leftFrame = leftCamera->getNextFrame();
				const auto &rightFrame = rightCamera->getNextFrame();
				if (leftFrame.has_value() && rightFrame.has_value())
				{
					writer.left.writeFrame(*leftFrame); 
					writer.right.writeFrame(*rightFrame);
				}
			}
			if (leftCamera->isImuStreamAvailable() && rightCamera->isImuStreamAvailable())
			{
				const auto &leftImu = leftCamera->getNextImuBatch();
				const auto &rightImu = rightCamera->getNextImuBatch();
				if (leftImu.has_value() && rightImu.has_value())
				{
					writer.left.writeImuPacket(*leftImu); 
					writer.right.writeImuPacket(*rightImu);
				}
			}
			if (leftCamera->isTriggerStreamAvailable() && rightCamera->isTriggerStreamAvailable())
			{
				const auto &leftTriggers = leftCamera->getNextTriggerBatch();
				const auto &rightTriggers = rightCamera->getNextTriggerBatch();
				if (leftTriggers.has_value() && rightTriggers.has_value())
				{
					writer.left.writeTriggerPacket(*leftTriggers); 
					writer.right.writeTriggerPacket(*rightTriggers);
				}
			}
		}
		// when recording finished, wake up consumer thread
		visQueueCondition.notify_all();
		if (showVisualization) {
			Log::info("Visualization frames dropped: ", droppedVisFrames.load(std::memory_order_relaxed));
		}
        Log::info("Recording Thread Finished");
	});

	dv::StereoEventStreamSlicer slicer;

	dv::visualization::EventVisualizer leftVis(leftCamera->getEventResolution().value());
	dv::visualization::EventVisualizer rightVis(rightCamera->getEventResolution().value());

	if (showVisualization)
	{
		cv::namedWindow("Left", cv::WINDOW_NORMAL);
		cv::namedWindow("Right", cv::WINDOW_NORMAL);
	}

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
					stopSignalDetection.store(true);
				}
			}
	});

	if (showVisualization)
	{
		// consumer
		while(!stopSignalDetection.load()) {
			StereoBatch batch;
			// use unique lock instead of scoped lock for dynamic locking and
			{
				std::unique_lock<std::mutex> lock(queueMutex);


				// // Wait for data OR timeout after 50ms to keep UI responsive
				// bool success = visQueueCondition.wait_for(lock, std::chrono::milliseconds(50), [&]{
				// 	return stopSignalDetection.load() || hasLatest;
				// });

				// if (stopSignalDetection.load() && !hasLatest) 
				// 	break;

				// if (success) {
				// 	batch = std::move(latest);
				// 	hasLatest = false;
				// }

				visQueueCondition.wait(lock, [&]{
					return stopSignalDetection.load() || hasLatest;
				});

				if (stopSignalDetection.load() && !hasLatest) 
					break;

				batch = std::move(latest);
				// unlock here so that the producer thread can push new data
				// while slicer is processing
				
				hasLatest = false;

			}
			if (batch.left && batch.right) {
				slicer.accept(*batch.left, *batch.right);
			} else 
			{
				// Even if no data came in, we must pump the GUI loop 
				// so the window doesn't freeze/turn grey
				cv::waitKey(1); 
			}
		}
	} 

	// Ensure worker thread stops
    stopSignalDetection.store(true);
	visQueueCondition.notify_all();
    
    if (recordingThread.joinable())
        recordingThread.join();

    if (showVisualization) 
	{
        cv::destroyAllWindows();
	}

	return EXIT_SUCCESS;

}

int environment_installed()
{
	// TODO change the way the path is handled here (maybe using make install
	// later)
	int result = system(SCRIPTS_DIR "check_env.sh");	
	int exit_code = 0;
    if (WIFEXITED(result)) 
	{
        exit_code = WEXITSTATUS(result);
    }
    if (exit_code == 0) 
	{
        Log::info("Environment found.");
		return EXIT_SUCCESS;
    } else if (exit_code == 1) 
	{
        Log::error("Environment E2VID missing.");
		return EXIT_FAILURE;
    } else 
	{
        Log::error("Conda missing or Script not found (Exit code: ", exit_code, ")");
		return EXIT_FAILURE;
	}	
    
	return EXIT_FAILURE;
}

int convertAedat4ToTxt(const std::filesystem::path& inputAedat4, const std::string& leftCamName, const std::string& rightCamName) 
{
	dv::io::StereoCameraRecording recording = dv::io::StereoCameraRecording(inputAedat4, leftCamName, rightCamName);
	
	if (recording.getLeftReader().isEventStreamAvailable() && recording.getRightReader().isEventStreamAvailable())
	{
		std::ofstream leftOutFile;
		leftOutFile.open("leftEvents.txt");
		leftOutFile << 640 << " " << 480 << "\n";
		// TODO which recording?!
		Log::info("Converting .aedat4 recording to .txt in preperation for E2VID:");
		Log::info("Processing left events...");
		uint16_t rightLineCount = 0;
		uint16_t leftLineCount = 0;
		while (true) {
			auto leftEvents = recording.getLeftReader().getNextEventBatch();
			// dv::EventStore sliced;
			// for (size_t i = 0; i < (leftEvents->size()-1); i++)
			// {
			// 	sliced = leftEvents->slice(i, i+1);
			// }
			if(!leftEvents.has_value())
				break;
			for (const dv::Event &ev : *leftEvents)
			{
				leftOutFile << ev.timestamp() << " " << ev.x() << " " << ev.y() << " " << ev.polarity() << "\n";		
				leftLineCount++;
			}
		}
		leftOutFile.close();

		std::ofstream rightOutFile;
		rightOutFile.open("rightEvents.txt");
		rightOutFile << 640 << " " << 480 << "\n";
		Log::info("Processing right events...");
		while (true) {
			auto rightEvents = recording.getRightReader().getNextEventBatch();
			if(!rightEvents.has_value())
				break;
			for (const dv::Event &ev : *rightEvents)
			{
				rightOutFile<< ev.timestamp() << " " << ev.x() << " " << ev.y() << " " << ev.polarity() << "\n";		
				rightLineCount++;
			}
		}
		rightOutFile.close();
		Log::info("Finished processing!\n","Left file has ", leftLineCount, " lines\n","Right file has ", rightLineCount, " lines");
	}

	return EXIT_SUCCESS;
}

int main (int argc, char *argv[])
{
	if (argc < 2)
	{
		logUsage(argv);
		return EXIT_FAILURE;
	}
	const std::string command = argv[1];
	if (command == "calibrate")
	{
		std::string inputPath, outputPath;
		std::string leftCamName = "DVXplorer_DXAS0054";
		std::string rightCamName = "DVXplorer_DXAS0051"; 

        for (int i = 2; i < argc; ++i) {
            std::string arg = argv[i];
            if ((arg == "-i" || arg == "--input") && i + 1 < argc) inputPath = argv[++i];
            else if ((arg == "-o" || arg == "--output") && i + 1 < argc) outputPath = argv[++i];
        }

        if (inputPath.empty() || outputPath.empty()) {
            Log::error("Error: Calibrate requires both -i and -o.");
            logUsage(argv);
            return EXIT_FAILURE;
        }	


		std::filesystem::path Location("./recordings/stereo_recording.aedat4");
		return convertAedat4ToTxt(Location, leftCamName, rightCamName);
		
	}
	else if (command == "capture")
	{		
		std::string pathString;
		bool visualize = false;
		for (int i = 2; i < argc; ++i)
		{
			std::string arg = argv[i];

			if(arg == "-v" || arg == "--visualize") 
				visualize = true;

			else if (arg == "-p" || arg == "--path")
			{
            	if (i + 1 < argc) 
				{
					pathString = argv[++i]; 
				} else 
				{
					Log::error("Error: ", arg," flag requires a path argument.");
                    logUsage(argv);
                    return EXIT_FAILURE;		
				}
			}
		}
		
		if (pathString.empty())
		{
			Log::error("Error: Path not specified.");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		const char* captureFolderName = "recordings";

		std::filesystem::path Location(pathString);
		std::filesystem::path fullPath = Location / captureFolderName;
		Log::info("The recording sessions will be saved under ", fullPath.string());
		if (visualize) 
			Log::info("Visualization enabled.");

		if(!std::filesystem::exists(fullPath))
		{	
			Log::warn("The provided path ", fullPath.string(), " does not exist. Do you want to create it? [Y/n]");

			const char response = (char)std::cin.get();
			if (response == '\n' || response == 'Y' || response == 'y')
			{
				Log::info("Creating path: ", fullPath.string());    
                try {
                    std::filesystem::create_directories(fullPath);
                } catch (const std::exception& e) {
                    Log::error("Failed to create directories: ", e.what());
                    return EXIT_FAILURE;
                }
			} 
			else 
				return EXIT_FAILURE;
		}

		return record(fullPath, visualize);	
	} else
	{
		logUsage(argv);
		return EXIT_FAILURE;
	}

	return EXIT_SUCCESS;
}
void logUsage(char* argv[])
{
    const std::string cmd = argv[0];
    Log::error("Usage: ", cmd, " <command> [options]\n\n",
               "Commands:\n",
               "  capture      Start recording\n",
               "  calibrate    Start calibration\n\n",
               "capture Options:\n",
               "  -p, --path <path>   (Required) output path\n",
               "  -v, --visualize     (Optional) enable preview\n\n",
			   "calibrate Options:\n"
			   "  -i, --input <path>   (Required) input path\n",
			   "  -o, --output <path>  (Required) output path");
}
