#include "Calibrator.h"
#include "FrameGenerator.h"
#include "Log.h"

namespace Calib
{
	int createRosBag(const std::filesystem::path& captureDir)
	{
		if (FrameGen::environment_installed() != EXIT_SUCCESS)
		{
			Log::error("Conda environment could not be found! Aborting...");
			return EXIT_FAILURE;
		}
		std::filesystem::path stereoFramesToBagScriptPath = std::filesystem::path(PROJECT_ROOT_DIR) / "src" / "python" / "stereo_frames_to_rosbag.py";

		std::string command = "conda run -n sert-python python3 " + stereoFramesToBagScriptPath.string() + " "
							+ "--path " + captureDir.string();

		Log::info("Executing: ", command);

		int result = std::system(command.c_str());
		return (result == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
	}

	int run(const Session& session, const std::filesystem::path& captureDir)
	{
		std::string command = std::string(SCRIPTS_DIR) + "run_kalibr.sh \"" 
							+ session.getPath().string() + "\" \"" 
							+ captureDir.string() + "\"";
		
		int result = std::system(command.c_str());	
		int exit_code = 0;
		if (WIFEXITED(result)) 
		{
			exit_code = WEXITSTATUS(result);
		}
		if (exit_code == 0) 
		{
			Log::info("Kalibr ran successfully! Check the results in: ", captureDir.string());
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
