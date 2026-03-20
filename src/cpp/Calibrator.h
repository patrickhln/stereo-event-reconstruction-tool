#pragma once
#include <filesystem>

namespace Calib
{
	int createRosBag(const std::filesystem::path& branchRoot);
	int run(const std::filesystem::path& branchRoot);
}
