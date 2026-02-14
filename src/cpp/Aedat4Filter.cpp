#include "Aedat4Filter.h"

#include "Log.h"

#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <stdexcept>

#include <dv-processing/core/filters.hpp>
#include <dv-processing/io/mono_camera_writer.hpp>
#include <dv-processing/io/stereo_camera_recording.hpp>
#include <dv-processing/io/stereo_camera_writer.hpp>
#include <dv-processing/noise/background_activity_noise_filter.hpp>
#include <dv-processing/noise/fast_decay_noise_filter.hpp>
#include <dv-processing/noise/k_noise_filter.hpp>

namespace
{
	bool chainContains(const std::vector<Aedat4Filter::FilterStep> &chain, const Aedat4Filter::FilterStage stage)
	{
		return std::any_of(chain.begin(), chain.end(), [stage](const Aedat4Filter::FilterStep &step) {
			return step.type == stage;
		});
	}

	dv::EventFilterChain<> createFilterChain(const cv::Size &resolution, const Aedat4Filter::FilterOptions &options,
		const std::optional<cv::Mat> &hotPixelMask)
	{
		dv::EventFilterChain<> filter;

		for (const Aedat4Filter::FilterStep &step : options.chain)
		{
			switch (step.type)
			{
				case Aedat4Filter::FilterStage::HOT_PIXEL:
					if (hotPixelMask.has_value())
					{
						filter.addFilter(std::make_shared<dv::EventMaskFilter<>>(hotPixelMask.value()));
					}
					break;
				case Aedat4Filter::FilterStage::ROI:
					if (options.roi.has_value())
					{
						filter.addFilter(std::make_shared<dv::EventRegionFilter<>>(options.roi.value()));
					}
					break;
				case Aedat4Filter::FilterStage::POLARITY:
					if (options.polarity.has_value())
					{
						filter.addFilter(std::make_shared<dv::EventPolarityFilter<>>(options.polarity.value()));
					}
					break;
				case Aedat4Filter::FilterStage::BACKGROUND_ACTIVITY:
					filter.addFilter(std::make_shared<dv::noise::BackgroundActivityNoiseFilter<>>(resolution, step.noiseTimeWindow));
					break;
				case Aedat4Filter::FilterStage::FAST_DECAY:
					filter.addFilter(std::make_shared<dv::noise::FastDecayNoiseFilter<>>(resolution, step.noiseTimeWindow));
					break;
				case Aedat4Filter::FilterStage::K_NOISE:
					filter.addFilter(std::make_shared<dv::noise::KNoiseFilter<>>(resolution, step.noiseTimeWindow));
					break;
			}
		}

		return filter;
	}
}

namespace Aedat4Filter
{
	StereoCameraNames readStereoCameraNames(const std::filesystem::path &metadataDirectory)
	{
		std::filesystem::path metadataPath = metadataDirectory / "camera_metadata.txt";
		std::ifstream metadataFile(metadataPath);
		if (!metadataFile.is_open())
		{
			throw std::runtime_error("Could not open camera metadata file: " + metadataPath.string());
		}

		StereoCameraNames names;
		std::string line;
		std::getline(metadataFile, line);
		if (!std::getline(metadataFile, names.leftCameraName) || names.leftCameraName.empty())
		{
			throw std::runtime_error("Could not read left camera name from: " + metadataPath.string());
		}

		std::getline(metadataFile, line);
		if (!std::getline(metadataFile, names.rightCameraName) || names.rightCameraName.empty())
		{
			throw std::runtime_error("Could not read right camera name from: " + metadataPath.string());
		}

		return names;
	}

	int filterStereoRecording(const std::filesystem::path &inputAedat4, const std::filesystem::path &outputAedat4,
		const StereoCameraNames &cameraNames, const FilterOptions &options)
	{
		if (!std::filesystem::exists(inputAedat4))
		{
			Log::error("Input recording does not exist: ", inputAedat4.string());
			return EXIT_FAILURE;
		}

		try
		{
			dv::io::StereoCameraRecording recording(inputAedat4, cameraNames.leftCameraName, cameraNames.rightCameraName);
			if (!recording.getLeftReader().isEventStreamAvailable() || !recording.getRightReader().isEventStreamAvailable())
			{
				Log::error("Input recording is missing stereo event streams.");
				return EXIT_FAILURE;
			}

			const std::optional<cv::Size> leftResolution = recording.getLeftReader().getEventResolution();
			const std::optional<cv::Size> rightResolution = recording.getRightReader().getEventResolution();
			if (!leftResolution.has_value() || !rightResolution.has_value())
			{
				Log::error("Could not read event stream resolution from input recording.");
				return EXIT_FAILURE;
			}

			std::optional<cv::Mat> leftHotPixelMask;
			std::optional<cv::Mat> rightHotPixelMask;
			if (chainContains(options.chain, Aedat4Filter::FilterStage::HOT_PIXEL))
			{
				const HotPixelFilter::StereoMasks masks = HotPixelFilter::detectStereoMasks(recording, options.hotPixelOptions);
				leftHotPixelMask = masks.leftKeepMask;
				rightHotPixelMask = masks.rightKeepMask;
				Log::info("Hot pixels detected - left: ", masks.leftHotPixelCount, ", right: ", masks.rightHotPixelCount);
			}

			const bool leftHasFrames = recording.getLeftReader().isFrameStreamAvailable();
			const bool rightHasFrames = recording.getRightReader().isFrameStreamAvailable();
			const bool leftHasImu = recording.getLeftReader().isImuStreamAvailable();
			const bool rightHasImu = recording.getRightReader().isImuStreamAvailable();
			const bool leftHasTriggers = recording.getLeftReader().isTriggerStreamAvailable();
			const bool rightHasTriggers = recording.getRightReader().isTriggerStreamAvailable();

			dv::io::MonoCameraWriter::Config leftConfig(cameraNames.leftCameraName);
			leftConfig.addEventStream(leftResolution.value());
			if (leftHasFrames)
			{
				const std::optional<cv::Size> leftFrameResolution = recording.getLeftReader().getFrameResolution();
				if (leftFrameResolution.has_value())
				{
					leftConfig.addFrameStream(leftFrameResolution.value());
				}
			}
			if (leftHasImu) { leftConfig.addImuStream(); }
			if (leftHasTriggers)
			{ leftConfig.addTriggerStream(); }

			dv::io::MonoCameraWriter::Config rightConfig(cameraNames.rightCameraName);
			rightConfig.addEventStream(rightResolution.value());
			if (rightHasFrames)
			{
				const std::optional<cv::Size> rightFrameResolution = recording.getRightReader().getFrameResolution();
				if (rightFrameResolution.has_value())
				{
					rightConfig.addFrameStream(rightFrameResolution.value());
				}
			}
			if (rightHasImu)
			{ rightConfig.addImuStream(); }
			if (rightHasTriggers)
			{ rightConfig.addTriggerStream(); }
			dv::io::StereoCameraWriter writer(outputAedat4, leftConfig, rightConfig);

			dv::EventFilterChain<> leftFilter = createFilterChain(leftResolution.value(), options, leftHotPixelMask);
			dv::EventFilterChain<> rightFilter = createFilterChain(rightResolution.value(), options, rightHotPixelMask);

			size_t leftIncomingEvents = 0;
			size_t leftOutgoingEvents = 0;
			size_t rightIncomingEvents = 0;
			size_t rightOutgoingEvents = 0;

			while (true)
			{
				const std::optional<dv::EventStore> leftBatch = recording.getLeftReader().getNextEventBatch();
				const std::optional<dv::EventStore> rightBatch = recording.getRightReader().getNextEventBatch();
				const std::optional<dv::Frame> leftFrame = leftHasFrames ? recording.getLeftReader().getNextFrame() : std::nullopt;
				const std::optional<dv::Frame> rightFrame = rightHasFrames ? recording.getRightReader().getNextFrame() : std::nullopt;
				const std::optional<std::vector<dv::IMU>> leftImuBatch = leftHasImu ? recording.getLeftReader().getNextImuBatch() : std::nullopt;
				const std::optional<std::vector<dv::IMU>> rightImuBatch = rightHasImu ? recording.getRightReader().getNextImuBatch() : std::nullopt;
				const std::optional<std::vector<dv::Trigger>> leftTriggerBatch = leftHasTriggers ? recording.getLeftReader().getNextTriggerBatch() : std::nullopt;
				const std::optional<std::vector<dv::Trigger>> rightTriggerBatch = rightHasTriggers ? recording.getRightReader().getNextTriggerBatch() : std::nullopt;

				if (!leftBatch.has_value() && !rightBatch.has_value() && !leftFrame.has_value() && !rightFrame.has_value()
					&& !leftImuBatch.has_value() && !rightImuBatch.has_value() && !leftTriggerBatch.has_value() && !rightTriggerBatch.has_value())
				{
					break;
				}

				if (leftBatch.has_value())
				{
					leftIncomingEvents += leftBatch->size();
					leftFilter.accept(leftBatch.value());
					dv::EventStore filtered = leftFilter.generateEvents();
					leftOutgoingEvents += filtered.size();
					writer.left.writeEvents(filtered);
				}

				if (rightBatch.has_value())
				{
					rightIncomingEvents += rightBatch->size();
					rightFilter.accept(rightBatch.value());
					dv::EventStore filtered = rightFilter.generateEvents();
					rightOutgoingEvents += filtered.size();
					writer.right.writeEvents(filtered);
				}

				if (leftFrame.has_value())
				{ writer.left.writeFrame(leftFrame.value()); }

				if (rightFrame.has_value())
				{ writer.right.writeFrame(rightFrame.value()); }

				if (leftImuBatch.has_value())
				{ writer.left.writeImu(leftImuBatch.value()); }

				if (rightImuBatch.has_value())
				{ writer.right.writeImu(rightImuBatch.value()); }

				if (leftTriggerBatch.has_value())
				{ writer.left.writeTriggers(leftTriggerBatch.value()); }

				if (rightTriggerBatch.has_value())
				{ writer.right.writeTriggers(rightTriggerBatch.value()); }
			}

			Log::info("Filtered stereo recording saved to: ", outputAedat4.string());
			Log::info("Left events: ", leftIncomingEvents, " -> ", leftOutgoingEvents);
			Log::info("Right events: ", rightIncomingEvents, " -> ", rightOutgoingEvents);
			return EXIT_SUCCESS;
		}
		catch (const std::exception &e)
		{
			Log::error("Filtering failed: ", e.what());
			return EXIT_FAILURE;
		}
	}
}
