#include "HotPixelFilter.h"

#include <stdexcept>

#include <dv-processing/core/core.hpp>
#include <dv-processing/io/mono_camera_recording.hpp>
#include <dv-processing/io/stereo_camera_recording.hpp>

// Hot Pixel Filtering inspired by: https://github.com/cedric-scheerlinck/dvs_tools/tree/master/dvs_hot_pixel_filter

namespace
{
	cv::Mat buildHistogram(dv::io::MonoCameraRecording &reader, const cv::Size &resolution)
	{
		cv::Mat histogram = cv::Mat::zeros(resolution, CV_64FC1);

		while (true)
		{
			const std::optional<dv::EventStore> batch = reader.getNextEventBatch();
			if (!batch.has_value())
			{
				break;
			}

			for (const dv::Event &event : batch.value())
			{
				histogram.at<double>(event.y(), event.x()) += 1.0;
			}
		}

		return histogram;
	}

	std::vector<cv::Point> detectByThreshold(const cv::Mat &histogram, const double nStdDev)
	{
		std::vector<cv::Point> hotPixels;
		const cv::Mat nonZeroMask = histogram > 0;
		if (cv::countNonZero(nonZeroMask) == 0)
		{
			return hotPixels;
		}

		cv::Scalar mean;
		cv::Scalar stdDev;
		cv::meanStdDev(histogram, mean, stdDev, nonZeroMask);
		const double threshold = mean[0] + (nStdDev * stdDev[0]);

		for (int y = 0; y < histogram.rows; y++)
		{
			for (int x = 0; x < histogram.cols; x++)
			{
				if (histogram.at<double>(y, x) >= threshold)
				{
					hotPixels.emplace_back(x, y);
				}
			}
		}

		return hotPixels;
	}

	std::vector<cv::Point> detectByTopN(const cv::Mat &histogram, const int nHotPixels)
	{
		std::vector<cv::Point> hotPixels;
		if (nHotPixels <= 0)
		{
			return hotPixels;
		}

		cv::Mat localHistogram;
		histogram.copyTo(localHistogram);

		for (int i = 0; i < nHotPixels; i++)
		{
			double maxValue = 0.0;
			cv::Point maxLocation;
			cv::minMaxLoc(localHistogram, nullptr, &maxValue, nullptr, &maxLocation);
			if (maxValue <= 0.0)
			{
				break;
			}

			hotPixels.push_back(maxLocation);
			localHistogram.at<double>(maxLocation) = 0.0;
		}

		return hotPixels;
	}
}

namespace HotPixelFilter
{
	std::vector<cv::Point> detectFromHistogram(const cv::Mat &histogram, const Options &options)
	{
		if (options.nHotPixels >= 0)
		{
			return detectByTopN(histogram, options.nHotPixels);
		}

		if (!options.autoDetect)
		{
			throw std::invalid_argument("Hot pixel filter requires nHotPixels >= 0 when autoDetect is false.");
		}

		return detectByThreshold(histogram, options.nStdDev);
	}

	cv::Mat createKeepMask(const cv::Size &resolution, const std::vector<cv::Point> &hotPixels)
	{
		cv::Mat keepMask(resolution, CV_8UC1, cv::Scalar(255));
		for (const cv::Point &pixel : hotPixels)
		{
			if (pixel.x >= 0 && pixel.x < keepMask.cols && pixel.y >= 0 && pixel.y < keepMask.rows)
			{
				keepMask.at<uint8_t>(pixel.y, pixel.x) = 0;
			}
		}
		return keepMask;
	}

	StereoMasks detectStereoMasks(dv::io::StereoCameraRecording &recording, const Options &options)
	{
		const std::optional<cv::Size> leftResolution = recording.getLeftReader().getEventResolution();
		const std::optional<cv::Size> rightResolution = recording.getRightReader().getEventResolution();
		if (!leftResolution.has_value() || !rightResolution.has_value())
		{
			throw std::runtime_error("Could not read stereo event resolution for hot pixel detection.");
		}

		const cv::Mat leftHistogram = buildHistogram(recording.getLeftReader(), leftResolution.value());
		const cv::Mat rightHistogram = buildHistogram(recording.getRightReader(), rightResolution.value());

		const std::vector<cv::Point> leftHotPixels = detectFromHistogram(leftHistogram, options);
		const std::vector<cv::Point> rightHotPixels = detectFromHistogram(rightHistogram, options);

		recording.getLeftReader().resetSequentialRead();
		recording.getRightReader().resetSequentialRead();

		StereoMasks result;
		result.leftKeepMask = createKeepMask(leftResolution.value(), leftHotPixels);
		result.rightKeepMask = createKeepMask(rightResolution.value(), rightHotPixels);
		result.leftHotPixelCount = leftHotPixels.size();
		result.rightHotPixelCount = rightHotPixels.size();
		return result;
	}
}
