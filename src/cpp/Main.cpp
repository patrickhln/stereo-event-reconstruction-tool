#include <atomic>
#include <csignal>
#include <cstdlib>
#include <string>
#include <fstream>
#include <vector>

#include "Log.h"
#include "Session.h"
#include "Recorder.h"
#include "FrameGenerator.h"
#include "Calibrator.h"
#include "Aedat4Filter.h"

void logUsage(char* argv[]);

static std::atomic<bool> stopSignal(false);

static void signalHandler(int)
{
	stopSignal.store(true);
}

int main (int argc, char *argv[])
{
	if (argc < 2)
	{
		logUsage(argv);
		return EXIT_FAILURE;
	}
	const std::string command = argv[1];

	std::signal(SIGINT, signalHandler);
	std::signal(SIGTERM, signalHandler);

	if (command == "render")
	{
		if (argc < 3)
		{
			Log::error("Error: render requires capture path");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			std::filesystem::path capturePath = std::filesystem::absolute(argv[2]);
			std::vector<std::string> e2vidArgs;
			for (int i = 3; i < argc; ++i)
			{
				std::string arg = argv[i];
				if (arg == "--")
				{
					for (++i; i < argc; ++i)
					{
						e2vidArgs.emplace_back(argv[i]);
					}
					break;
				}
				Log::error("Unknown render option: ", arg, ". Use '--' before E2VID args.");
				return EXIT_FAILURE;
			}
			if (!std::filesystem::exists(capturePath))
			{
				Log::error("Error: Capture path does not exist: ", capturePath.string());
				return EXIT_FAILURE;
			}

			Session session = Session::load(Session::findSessionRoot(capturePath));
			
			std::filesystem::path rawDir = Session::getRawDir(capturePath);
			std::filesystem::path intermediateDir = Session::getIntermediateDir(capturePath);
			std::filesystem::path framesDir = Session::getFramesDir(capturePath);

			if (!std::filesystem::exists(rawDir))
			{
				Log::error("Invalid capture: 'raw' directory missing in ", capturePath.string());
				return EXIT_FAILURE;
			}

			std::filesystem::create_directories(intermediateDir);
			std::filesystem::create_directories(framesDir);

			FrameGen::CameraMetadata meta = FrameGen::readMetadata(rawDir);

			std::filesystem::path recordingFile = rawDir / "stereo_recording.aedat4";
			if (FrameGen::convertAedat4ToTxt(recordingFile, intermediateDir, meta.leftCamName, meta.rightCamName) != EXIT_SUCCESS)
			{
				Log::error("Could not convert .aedat4 to .txt for further E2VID reconstruction. Aborting...");	
				return EXIT_FAILURE;
			}
			if (FrameGen::recordingToVideo(intermediateDir, framesDir, e2vidArgs) != EXIT_SUCCESS)
			{
				Log::error("E2VID reconstruction failed. Aborting...");
				return EXIT_FAILURE;
			}
		}
		catch (const std::exception& e)
		{
			Log::error("Error: ", e.what());
			return EXIT_FAILURE;
		}
	}
	else if (command == "filter")
	{
		if (argc < 3)
		{
			Log::error("Error: filter requires an input .aedat4 file");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			std::string configArg;
			for (int i = 3; i < argc; ++i)
			{
				std::string arg = argv[i];
				if (arg == "--config")
				{
					if (i + 1 >= argc)
					{
						Log::error("Error: --config requires a value");
						return EXIT_FAILURE;
					}
					configArg = argv[++i];
				}
				else
				{
					Log::error("Unknown filter option: ", arg);
					return EXIT_FAILURE;
				}
			}

			if (configArg.empty())
			{
				Log::error("Error: filter requires --config <path/to/config.yaml>");
				return EXIT_FAILURE;
			}

			std::filesystem::path inputAedat4 = argv[2];
			if (!inputAedat4.is_absolute())
			{
				const std::filesystem::path cwdPath = std::filesystem::absolute(inputAedat4);
				inputAedat4 = std::filesystem::exists(cwdPath) ? cwdPath : (std::filesystem::path(PROJECT_ROOT_DIR) / inputAedat4);
			}
			inputAedat4 = inputAedat4.lexically_normal();

			if (!std::filesystem::is_regular_file(inputAedat4) || inputAedat4.extension() != ".aedat4")
			{
				Log::error("Error: Input must be an existing .aedat4 file: ", inputAedat4.string());
				return EXIT_FAILURE;
			}

			const std::filesystem::path rawDir = inputAedat4.parent_path();
			std::filesystem::path configPath = std::filesystem::path(configArg);
			if (!configPath.is_absolute())
			{
				configPath = std::filesystem::absolute(configPath);
			}
			configPath = configPath.lexically_normal();
			if (configPath.extension() != ".yaml")
			{
				Log::error("Error: --config must point to a .yaml file: ", configPath.string());
				return EXIT_FAILURE;
			}
			if (!std::filesystem::is_regular_file(configPath))
			{
				Log::error("Error: Filter config not found: ", configPath.string());
				return EXIT_FAILURE;
			}

			const std::filesystem::path filteredDir = rawDir / "filtered";
			std::filesystem::create_directories(filteredDir);
			const std::filesystem::path outputAedat4 = filteredDir /
				(inputAedat4.stem().string() + "__" + configPath.stem().string() + ".aedat4");

			const Aedat4Filter::FilterOptions options = Aedat4Filter::loadFilterOptionsFromYaml(configPath);

			const Aedat4Filter::StereoCameraNames cameraNames = Aedat4Filter::readStereoCameraNames(rawDir);
			return Aedat4Filter::filterStereoRecording(inputAedat4, outputAedat4, cameraNames, options);
		}
		catch (const std::exception &e)
		{
			Log::error("Error: ", e.what());
			return EXIT_FAILURE;
		}
	}
	else if (command == "record")
	{		
		std::string sessionPathArg;
		std::string captureName;
		std::string captureType;
		bool visualize = false;

		// First non-flag arg is session path (optional)
		int i = 2;
		if (i < argc && argv[i][0] != '-')
			sessionPathArg = argv[i++];

		for (; i < argc; ++i)
		{
			std::string arg = argv[i];
			if (arg == "-v" || arg == "--visualize") visualize = true;
			else if ((arg == "-n" || arg == "--name") && i + 1 < argc) captureName = argv[++i];
			else if ((arg == "-t" || arg == "--type") && i + 1 < argc) captureType = argv[++i];
		}

		if (captureType.empty() || (captureType != "calib" && captureType != "scene"))
		{
			Log::error("Error: Must specify -t calib or -t scene");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			std::filesystem::path sessionPath = sessionPathArg.empty() 
				? std::filesystem::current_path() 
				: std::filesystem::absolute(sessionPathArg);

			Session session = Session::isValidSession(sessionPath)
				? Session::load(sessionPath)
				: (std::filesystem::create_directories(sessionPath), 
				   Session::create(sessionPath.parent_path(), sessionPath.filename().string()));

			CaptureType type = (captureType == "calib") ? CaptureType::CALIBRATION : CaptureType::SCENE;
			std::filesystem::path captureDir = session.createCapture(type, captureName);
			std::filesystem::path rawDir = Session::getRawDir(captureDir);

			if (visualize) 
				Log::info("Visualization enabled.");

			return StereoRecorder::record(rawDir, visualize, stopSignal);
		}
		catch (const std::exception& e)
		{
			Log::error("Error: ", e.what());
			return EXIT_FAILURE;
		}
	}
	else if (command == "calibrate")
	{
		if (argc < 3)
		{
			Log::error("Error: calibrate requires capture path");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		std::string capturePathArg = argv[2];
		std::string targetType;
		int cols = 0, rows = 0;
		float param3 = 0.0f, param4 = 0.0f;
		bool configProvided = false;

		for (int i = 3; i < argc; ++i) 
		{
			std::string arg = argv[i];
			if ((arg == "-t" || arg == "--target") && i + 1 < argc) targetType = argv[++i];
			if ((arg == "--config") && i + 4 < argc)
			{
				try 
				{
					cols = std::stoi(argv[++i]);    
					rows = std::stoi(argv[++i]);    
					param3 = std::stof(argv[++i]);    
					param4 = std::stof(argv[++i]);
					configProvided = true;
				} catch (const std::exception& e) 
				{
					Log::error("Invalid numeric value in config: ", e.what());
					return EXIT_FAILURE;
				}
			}
		}

		try
		{
			std::filesystem::path capturePath = std::filesystem::absolute(capturePathArg);
			if (!std::filesystem::exists(capturePath))
			{
				Log::error("Error: Capture path does not exist: ", capturePath.string());
				return EXIT_FAILURE;
			}

			Session session = Session::load(Session::findSessionRoot(capturePath));
			std::string captureName = capturePath.filename().string();
			
			std::filesystem::path framesDir = Session::getFramesDir(capturePath);
			std::filesystem::path configDir = session.getTargetsDir();

			if (!std::filesystem::exists(framesDir))
			{
				Log::error("Invalid capture: 'frames' directory missing in ", capturePath.string());
				Log::error("Run 'sert render' first to generate frames.");
				return EXIT_FAILURE;
			}

			// check for existing target config
			bool configExists = false;
			if (std::filesystem::exists(configDir))
			{
				for (const auto& entry : std::filesystem::directory_iterator(configDir))
				{
					std::string filename = entry.path().filename().string();
					if (filename == "aprilgrid.yaml" || filename == "checkerboard.yaml" || filename == "circlegrid.yaml")
					{
						configExists = true;
						Log::info("Found existing calibration target config: ", entry.path().string());
						break;
					}
				}
			}

			if (!configExists && (targetType.empty() || !configProvided))
			{
				Log::error("Error: No existing calibration config found. Please provide -t and --config options.");
				logUsage(argv);
				return EXIT_FAILURE;
			}

			std::filesystem::create_directories(configDir);
			Log::info("Initialized calibration for capture: ", captureName);

			// write target config if provided
			if (!targetType.empty() && configProvided)
			{
				if (targetType == "aprilgrid")
				{
					std::ofstream cfg(configDir / "aprilgrid.yaml");
					cfg << "target_type: 'aprilgrid'\ntagCols: " << cols << "\ntagRows: " << rows 
					    << "\ntagSize: " << param3 << "\ntagSpacing: " << param4 << "\n";
				}
				else if (targetType == "checkerboard") 
				{
					std::ofstream cfg(configDir / "checkerboard.yaml");
					cfg << "target_type: 'checkerboard'\ntargetCols: " << cols << "\ntargetRows: " << rows 
					    << "\nrowSpacingMeters: " << param3 << "\ncolSpacingMeters: " << param4 << "\n";
				}
				else if (targetType == "circlegrid") 
				{
					std::ofstream cfg(configDir / "circlegrid.yaml");
					cfg << "target_type: 'circlegrid'\ntargetCols: " << cols << "\ntargetRows: " << rows 
					    << "\nspacingMeters: " << param3 << "\nasymmetricGrid: " << (param4 ? "True" : "False") << "\n";
				}
				else 
				{
					Log::error("Target type must be: aprilgrid, checkerboard, or circlegrid");
					return EXIT_FAILURE;
				}
			}

			if (Calib::createRosBag(capturePath) != EXIT_SUCCESS)
			{
				Log::error("Failed to create ROS bag for calibration.");
				return EXIT_FAILURE;
			}

			if (Calib::run(session, capturePath) != EXIT_SUCCESS)
			{
				Log::error("Calibration failed.");
				return EXIT_FAILURE;
			}

			try
			{
				session.setActiveCalibration(captureName);
				Log::info("Calibration successful! Set '", captureName, "' as active calibration.");
			}
			catch (const std::exception& e)
			{
				Log::warn("Calibration completed but could not auto-activate: ", e.what());
			}
		}
		catch (const std::exception& e)
		{
			Log::error("Error: ", e.what());
			return EXIT_FAILURE;
		}
	}
	else if (command == "set-calibration")
	{
		if (argc < 3)
		{
			Log::error("Error: set-calibration requires calibration path");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			std::filesystem::path calibPath = std::filesystem::absolute(argv[2]);
			if (!std::filesystem::exists(calibPath))
			{
				Log::error("Error: Calibration path does not exist: ", calibPath.string());
				return EXIT_FAILURE;
			}

			Session session = Session::load(Session::findSessionRoot(calibPath));
			session.setActiveCalibration(calibPath.filename().string());
		}
		catch (const std::exception& e)
		{
			Log::error("Error: ", e.what());
			return EXIT_FAILURE;
		}
	}
	else
	{
		logUsage(argv);
		return EXIT_FAILURE;
	}
	return EXIT_SUCCESS;
}

void logUsage(char* argv[])
{
	const std::string cmd = argv[0];
	Log::info(
		"Usage: ", cmd, " <command> [args]\n\n",

		"Commands:\n",
		"  record [<session>] -t calib|scene [-n <name>] [-v]\n",
		"      Record to calibration or scene capture\n",
		"      <session>  Session directory (default: current directory)\n",
		"                 Creates session if it doesn't exist\n",
		"      -t         Capture type: 'calib' or 'scene' (required)\n",
		"      -n         Custom capture name (optional)\n",
		"      -v         Enable live preview (optional)\n\n",

		"  render <capture> [-- <e2vid_args...>]\n",
		"      Generate frames from events using E2VID\n",
		"      <capture>  Path to capture directory\n",
		"      --         Pass remaining args directly to rpg_e2vid/run_reconstruction.py\n",
		"      		      -> E2VID args can be found at https://github.com/uzh-rpg/rpg_e2vid\n\n"

		"  filter <recording.aedat4> --config <path/to/config.yaml>\n",
		"      Apply event filter chain from explicit YAML config path\n",
		"      Writes output to raw/filtered/<recording>__<config>.aedat4\n\n",

		"  calibrate <capture> [-t <target> --config <args>]\n",
		"      Run Kalibr calibration on capture\n",
		"      <capture>  Path to calibration capture\n",
		"      -t         Target type: aprilgrid, checkerboard, circlegrid\n",
		"      --config   Target config (required if no existing config):\n",
		"                   aprilgrid:    <cols> <rows> <tagSize> <tagSpacing>\n",
		"                   checkerboard: <cols> <rows> <rowSpacing> <colSpacing>\n",
		"                   circlegrid:   <cols> <rows> <spacing> <asymmetric 0/1>\n\n",

		"  set-calibration <calibration>\n",
		"      Set active calibration for session\n",
		"      <calibration>  Path to calibration directory\n\n",

		"Examples:\n",
		"  ", cmd, " record -t calib                    # Record calib in current session\n",
		"  ", cmd, " record lab -t scene -n outdoor     # Create 'lab/' and record scene\n",
		"  ", cmd, " render lab/calibrations/calib_01   # Generate frames (default settings)\n",
		"  ", cmd, " render lab/calibrations/calib_01 -- --window_duration 20 --auto_hdr\n",
		"  ", cmd, " filter lab/scenes/scene_01/raw/stereo_recording.aedat4 --config lab/config/filters/default.yaml\n",
		"  ", cmd, " filter lab/scenes/scene_01/raw/stereo_recording.aedat4 --config ./custom_filters/my_chain.yaml\n",
		"  ", cmd, " calibrate lab/calibrations/calib_01 -t checkerboard --config 8 6 0.068 0.068\n",
		"  ", cmd, " set-calibration lab/calibrations/calib_01\n"
	);
}
