#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <string>
#include <thread>

#include <dv-processing/core/core.hpp>
#include <dv-processing/core/stereo_event_stream_slicer.hpp>
#include <dv-processing/io/stereo_camera_recording.hpp>
#include <dv-processing/visualization/event_visualizer.hpp>

#include <opencv2/highgui.hpp>

namespace
{
	struct StereoCameraNames
	{
		std::string left;
		std::string right;
	};

	struct PreviewMetrics
	{
		std::size_t frames = 0;
		double displayHz = 0.0;
		std::chrono::steady_clock::time_point lastUpdate = std::chrono::steady_clock::now();

		bool tick()
		{
			++frames;
			const auto now = std::chrono::steady_clock::now();
			const double elapsed = std::chrono::duration<double>(now - lastUpdate).count();
			if (elapsed < 1.0)
			{
				return false;
			}
			displayHz = static_cast<double>(frames) / elapsed;
			frames = 0;
			lastUpdate = now;
			return true;
		}

		// TODO: extend with event-rate and smoothing metrics.
	};

	std::optional<StereoCameraNames> readCameraNames(const std::filesystem::path &metadataPath)
	{
		std::ifstream metadataFile(metadataPath);
		if (!metadataFile.is_open())
		{
			return std::nullopt;
		}

		StereoCameraNames names;
		std::string line;
		std::getline(metadataFile, line);
		std::getline(metadataFile, names.left);
		std::getline(metadataFile, line);
		std::getline(metadataFile, names.right);
		if (names.left.empty() || names.right.empty())
		{
			return std::nullopt;
		}
		return names;
	}

}

int main(int argc, char **argv)
{
	if (argc < 2)
	{
		std::cerr << "Usage: aedat4_stereo_preview <recording.aedat4|raw_dir> [speed]\n";
		std::cerr << "Example speed: 0.1 (10%), 1.0 (realtime), 2.0 (2x)\n";
		return EXIT_FAILURE;
	}

	std::filesystem::path input = argv[1];
	std::filesystem::path recordingPath = std::filesystem::is_directory(input) ? input / "stereo_recording.aedat4" : input;
	std::filesystem::path metadataPath = std::filesystem::is_directory(input) ? input / "camera_metadata.txt" : input.parent_path() / "camera_metadata.txt";
	if (!std::filesystem::exists(recordingPath))
	{
		std::cerr << "Recording not found: " << recordingPath << "\n";
		return EXIT_FAILURE;
	}

	const auto cameraNames = readCameraNames(metadataPath);
	if (!cameraNames.has_value())
	{
		std::cerr << "Could not read camera names from: " << metadataPath << "\n";
		return EXIT_FAILURE;
	}

	double speed = (argc >= 3) ? std::atof(argv[2]) : 1.0;
	if (speed <= 0.0)
	{
		speed = 1.0;
	}

	dv::io::StereoCameraRecording recording(recordingPath, cameraNames->left, cameraNames->right);
	if (!recording.getLeftReader().isEventStreamAvailable() || !recording.getRightReader().isEventStreamAvailable())
	{
		std::cerr << "Recording is missing left/right event streams.\n";
		return EXIT_FAILURE;
	}

	const auto leftResolution = recording.getLeftReader().getEventResolution();
	const auto rightResolution = recording.getRightReader().getEventResolution();
	if (!leftResolution.has_value() || !rightResolution.has_value())
	{
		std::cerr << "Could not read event resolutions from recording.\n";
		return EXIT_FAILURE;
	}

	dv::visualization::EventVisualizer leftVis(leftResolution.value());
	dv::visualization::EventVisualizer rightVis(rightResolution.value());
	dv::StereoEventStreamSlicer slicer;
	PreviewMetrics metrics;

	const int renderHz = 60;
	const auto wallFramePeriod = std::chrono::microseconds(1000000 / renderHz);
	const auto recordingSliceUs = std::max<int64_t>(1, static_cast<int64_t>(wallFramePeriod.count() * speed));
	auto nextFrameTime = std::chrono::steady_clock::now();

	const std::string windowName = recordingPath / " Preview";
	cv::namedWindow(windowName, cv::WINDOW_NORMAL);

	bool shouldStop = false;
	slicer.doEveryTimeInterval(dv::Duration(recordingSliceUs), [&](const dv::EventStore &leftEvents, const dv::EventStore &rightEvents) {
		std::this_thread::sleep_until(nextFrameTime);
		nextFrameTime += wallFramePeriod;
		if (nextFrameTime < std::chrono::steady_clock::now())
		{
			nextFrameTime = std::chrono::steady_clock::now();
		}

		cv::Mat preview;
		cv::hconcat(leftVis.generateImage(leftEvents), rightVis.generateImage(rightEvents), preview);
		cv::imshow(windowName, preview);

		if (metrics.tick())
		{
			std::cout << "\rSpeed x" << speed << " | preview " << metrics.displayHz << " Hz" << std::flush;
		}

		const int key = cv::waitKey(1);
		if (key == 27 || key == 'q')
		{
			shouldStop = true;
		}
	});

	while (!shouldStop)
	{
		const auto leftBatch = recording.getLeftReader().getNextEventBatch();
		const auto rightBatch = recording.getRightReader().getNextEventBatch();
		if (!leftBatch.has_value() && !rightBatch.has_value())
		{
			break;
		}

		slicer.accept(leftBatch.value_or(dv::EventStore()), rightBatch.value_or(dv::EventStore()));
	}

	std::cout << "\n";
	cv::destroyAllWindows();
	return EXIT_SUCCESS;
}
