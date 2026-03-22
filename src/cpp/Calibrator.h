#pragma once
#include <filesystem>
#include <string>

namespace Calib
{
	int createRosBag(const std::filesystem::path& branchRoot, const std::string& model);
	int run(const std::filesystem::path& branchRoot, const std::string& model);
}
