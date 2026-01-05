#pragma once
#include <filesystem>
#include <atomic>

namespace StereoRecorder 
{
	int record(const std::filesystem::path &rawDir, bool showVisualization, std::atomic<bool>& stopSignal);
}
