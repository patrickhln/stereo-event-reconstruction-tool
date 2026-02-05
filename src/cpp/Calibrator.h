#pragma once
#include <filesystem>
#include "Session.h"

namespace Calib
{
	int createRosBag(const std::filesystem::path& captureDir);
	int run(const Session& session, const std::filesystem::path& captureDir);
}
