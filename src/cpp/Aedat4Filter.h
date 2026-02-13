#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

#include <opencv2/core/types.hpp>

#include <dv-processing/core/core.hpp>

#include "HotPixelFilter.h"

namespace Aedat4Filter
{
	enum class FilterStage
	{
		HOT_PIXEL,
		ROI,
		POLARITY,
		BACKGROUND_ACTIVITY,
		FAST_DECAY,
		K_NOISE
	};

	struct FilterStep
	{
		FilterStage type;
		dv::Duration noiseTimeWindow = dv::Duration(2000);
	};

	struct FilterOptions
	{
		std::vector<FilterStep> chain{};
		HotPixelFilter::Options hotPixelOptions;
		std::optional<cv::Rect> roi;
		std::optional<bool> polarity;
	};

	struct StereoCameraNames
	{
		std::string leftCameraName;
		std::string rightCameraName;
	};

	StereoCameraNames readStereoCameraNames(const std::filesystem::path &metadataDirectory);

	int filterStereoRecording(const std::filesystem::path &inputAedat4, const std::filesystem::path &outputAedat4,
		const StereoCameraNames &cameraNames, const FilterOptions &options = {});
}
