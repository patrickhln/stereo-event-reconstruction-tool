#pragma once
#include <filesystem>

namespace Calib
{
	int createRosBag(const std::filesystem::path sessionPath);
	int run(const std::filesystem::path sessionPath);
}
