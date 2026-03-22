#include "Calibrator.h"
#include "FrameGenerator.h"
#include "Log.h"

#include <cstdlib>
#include <sys/wait.h>

namespace
{
	std::string shellQuote(const std::string &value)
	{
		std::string quoted = "'";
		for (char c : value)
		{
			if (c == '\'')
			{
				quoted += "'\\''";
			}
			else
			{
				quoted += c;
			}
		}
		quoted += "'";
		return quoted;
	}
}

namespace Calib
{
	int createRosBag(const std::filesystem::path& branchRoot, const std::string& model)
	{
		if (FrameGen::environment_installed() != EXIT_SUCCESS)
		{
			Log::error("Conda environment could not be found! Aborting...");
			return EXIT_FAILURE;
		}
		std::filesystem::path stereoFramesToBagScriptPath = std::filesystem::path(PROJECT_ROOT_DIR) / "src" / "python" / "stereo_frames_to_rosbag.py";

		std::string command = "conda run -n sert-python python3 " + shellQuote(stereoFramesToBagScriptPath.string()) + " "
							+ "--path " + shellQuote(branchRoot.string()) + " "
							+ "--model " + shellQuote(model);

		Log::info("Executing: ", command);

		int result = std::system(command.c_str());
		return (result == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
	}

	int run(const std::filesystem::path& branchRoot, const std::string& model)
	{
		std::filesystem::path scriptPath = std::filesystem::path(SCRIPTS_DIR) / "run_kalibr.sh";
		std::string command = shellQuote(scriptPath.string()) + " "
							+ shellQuote(branchRoot.string()) + " "
							+ shellQuote(model);
		
		int result = std::system(command.c_str());	
		int exit_code = 0;
		if (WIFEXITED(result)) 
		{
			exit_code = WEXITSTATUS(result);
		}
		if (exit_code == 0) 
		{
			Log::info("Kalibr ran successfully! Check the results in: ", (branchRoot / "calibration" / model).string());
			return EXIT_SUCCESS;
		} else if (exit_code == 1) 
		{
			Log::error("Ran into an issue running kalibr");
			return EXIT_FAILURE;
		} else 
		{
			Log::error("Conda missing or Script not found (Exit code: ", exit_code, ")");
			return EXIT_FAILURE;
		}	
		
		return EXIT_FAILURE;
	}
}
