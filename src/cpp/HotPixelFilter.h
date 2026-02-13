#pragma once

#include <cstddef>
#include <vector>

#include <opencv2/core/mat.hpp>
#include <opencv2/core/types.hpp>

namespace dv::io
{
	class MonoCameraRecording;
	class StereoCameraRecording;
}

namespace HotPixelFilter
{
	struct Options
	{
		bool autoDetect = true;
		int nHotPixels = -1;
		double nStdDev = 5.0;
	};

	struct StereoMasks
	{
		cv::Mat leftKeepMask;
		cv::Mat rightKeepMask;
		size_t leftHotPixelCount = 0;
		size_t rightHotPixelCount = 0;
	};

	std::vector<cv::Point> detectFromHistogram(const cv::Mat &histogram, const Options &options);

	cv::Mat createKeepMask(const cv::Size &resolution, const std::vector<cv::Point> &hotPixels);

	StereoMasks detectStereoMasks(dv::io::StereoCameraRecording &recording, const Options &options);
}
