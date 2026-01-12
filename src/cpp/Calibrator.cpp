#include "Calibrator.h"
#include "FrameGenerator.h"
#include "Log.h"

namespace Calib
{
	int createRosBag(const std::filesystem::path sessionPath)
	{
		if (FrameGen::environment_installed() != EXIT_SUCCESS)
		{
			Log::error("Conda environment could not be found! Aborting...");
			return EXIT_FAILURE;
		}
		std::filesystem::path stereoFramesToBagScriptPath = std::filesystem::path(PROJECT_ROOT_DIR) / "src" / "python" / "stereo_frames_to_rosbag.py";

		std::string command = "conda run -n sert-python python3 " + stereoFramesToBagScriptPath.string() + " "
							+ "--path " + sessionPath.string();

		Log::info("Executin: ", command);

		int result = std::system(command.c_str());
		return (result == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
	}
	int run(const std::filesystem::path sessionPath)
	{
		std::string command = std::string(SCRIPTS_DIR) + "run_kalibr.sh \"" + sessionPath.string() + "\"";
		int result = std::system(command.c_str());	
		int exit_code = 0;
		if (WIFEXITED(result)) 
		{
			exit_code = WEXITSTATUS(result);
		}
		if (exit_code == 0) 
		{
			Log::info("Kalibr ran successfully! Check the results under <session>/calibration");
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
