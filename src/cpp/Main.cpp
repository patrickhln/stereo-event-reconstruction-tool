#include <atomic>
#include <csignal>
#include <cstdlib>
#include <filesystem>
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

static bool isSupportedModel(const std::string &model)
{
	return model == "e2vid" || model == "e2vidplus" || model == "e2vidplusupdate" || model == "firenet";
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
			Log::error("Error: render requires capture path (group root or branch root)");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			std::filesystem::path inputPath = std::filesystem::absolute(argv[2]);
			FrameGen::RenderOptions renderOpts;
			for (int i = 3; i < argc; ++i)
			{
				std::string arg = argv[i];
				if (arg == "--model" && i + 1 < argc)
				{
					renderOpts.model = argv[++i];
				}
				else if (arg == "--device" && i + 1 < argc)
				{
					renderOpts.device = argv[++i];
				}
				else if (arg == "--")
				{
					for (++i; i < argc; ++i)
					{
						renderOpts.extraArgs.emplace_back(argv[i]);
					}
					break;
				}
				else
				{
					Log::error("Unknown render option: ", arg, ". Use '--' before extra backend args.");
					return EXIT_FAILURE;
				}
			}

			if (!isSupportedModel(renderOpts.model))
			{
				Log::error("Unknown model: ", renderOpts.model, ". Supported models: e2vid, e2vidplus, e2vidplusupdate, firenet.");
				return EXIT_FAILURE;
			}

			if (renderOpts.device != "auto" && renderOpts.device != "cpu" && renderOpts.device != "xpu" && renderOpts.device != "cuda")
			{
				Log::error("Unknown device: ", renderOpts.device, ". Supported devices: auto, cpu, xpu, cuda.");
				return EXIT_FAILURE;
			}
			if (!std::filesystem::exists(inputPath))
			{
				Log::error("Error: Path does not exist: ", inputPath.string());
				return EXIT_FAILURE;
			}

			std::filesystem::path branchRoot = Session::resolveBranchRoot(inputPath);
			Session session = Session::load(Session::findSessionRoot(branchRoot));

			std::filesystem::path rawDir = Session::getRawDir(branchRoot);
			std::filesystem::path intermediateDir = Session::getIntermediateDir(branchRoot);
			std::filesystem::path framesDir = Session::getFramesDir(branchRoot);

			if (!std::filesystem::exists(rawDir))
			{
				Log::error("Invalid branch: 'raw' directory missing in ", branchRoot.string());
				return EXIT_FAILURE;
			}

			std::filesystem::create_directories(intermediateDir);
			std::filesystem::create_directories(framesDir);

			Log::info("Rendering branch: ", branchRoot.string());
			Log::info("Rendering model: ", renderOpts.model);

			FrameGen::CameraMetadata meta = FrameGen::readMetadata(rawDir);

			std::filesystem::path recordingFile = rawDir / "stereo_recording.aedat4";
			if (FrameGen::convertAedat4ToTxt(recordingFile, intermediateDir, meta.leftCamName, meta.rightCamName) != EXIT_SUCCESS)
			{
				Log::error("Could not convert .aedat4 to .txt for reconstruction. Aborting...");	
				return EXIT_FAILURE;
			}
			if (FrameGen::recordingToVideo(intermediateDir, framesDir, renderOpts) != EXIT_SUCCESS)
			{
				Log::error("Reconstruction failed. Aborting...");
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
			Log::error("Error: filter requires a capture group or branch root path");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		std::filesystem::path createdBranchRoot;
		bool createdBranch = false;

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

			// Resolve input path to a branch root
			std::filesystem::path inputPath = std::filesystem::absolute(argv[2]);
			if (!std::filesystem::exists(inputPath))
			{
				Log::error("Error: Path does not exist: ", inputPath.string());
				return EXIT_FAILURE;
			}

			std::filesystem::path sourceBranch = Session::resolveBranchRoot(inputPath);

			// Only allow filtering from unfiltered branch
			if (sourceBranch.filename().string() != Session::UNFILTERED_BRANCH)
			{
				Log::error("Error: Filtering currently only derives from the '", Session::UNFILTERED_BRANCH, "' branch.");
				Log::error("You provided: ", sourceBranch.string());
				Log::error("Chained filtering (filtered -> filtered) is not supported yet.");
				return EXIT_FAILURE;
			}

			// Resolve config path
			std::filesystem::path configPath = std::filesystem::absolute(configArg);
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

			// Determine branch name from config stem
			std::string configStem = configPath.stem().string();
			std::string newBranchName = Session::filteredBranchName(configStem);
			std::filesystem::path groupRoot = sourceBranch.parent_path();
			std::filesystem::path newBranchRoot = groupRoot / newBranchName;

			// Check if branch already exists
			if (std::filesystem::exists(newBranchRoot))
			{
				Log::error("Error: Branch already exists: ", newBranchRoot.string());
				Log::error("Will not overwrite. Remove it manually or use a different config.");
				return EXIT_FAILURE;
			}

			// Determine capture type
			Session session = Session::load(Session::findSessionRoot(sourceBranch));
			CaptureType captureType = session.detectCaptureType(sourceBranch);

			// Create new branch directory structure
			Session::createBranchDirs(newBranchRoot, captureType);
			createdBranchRoot = newBranchRoot;
			createdBranch = true;
			Log::info("Created filtered branch: ", newBranchRoot.string());

			// Source and destination paths
			std::filesystem::path sourceRaw = Session::getRawDir(sourceBranch);
			std::filesystem::path destRaw = Session::getRawDir(newBranchRoot);
			std::filesystem::path inputAedat4 = sourceRaw / "stereo_recording.aedat4";
			std::filesystem::path outputAedat4 = destRaw / "stereo_recording.aedat4";

			if (!std::filesystem::exists(inputAedat4))
			{
				Log::error("Error: Source recording not found: ", inputAedat4.string());
				// Clean up the created branch
				std::filesystem::remove_all(newBranchRoot);
				return EXIT_FAILURE;
			}

			// Copy camera metadata to new branch
			std::filesystem::path sourceMetadata = sourceRaw / "camera_metadata.txt";
			std::filesystem::path destMetadata = destRaw / "camera_metadata.txt";
			if (std::filesystem::exists(sourceMetadata))
			{
				std::filesystem::copy_file(sourceMetadata, destMetadata, std::filesystem::copy_options::overwrite_existing);
			}

			// Load filter options and run
			const Aedat4Filter::FilterOptions options = Aedat4Filter::loadFilterOptionsFromYaml(configPath);
			const Aedat4Filter::StereoCameraNames cameraNames = Aedat4Filter::readStereoCameraNames(sourceRaw);

			Log::info("Filtering: ", inputAedat4.string());
			Log::info("      ->   ", outputAedat4.string());

			int result = Aedat4Filter::filterStereoRecording(inputAedat4, outputAedat4, cameraNames, options);
			if (result != EXIT_SUCCESS)
			{
				Log::error("Filtering failed. Cleaning up branch: ", newBranchRoot.string());
				std::filesystem::remove_all(newBranchRoot);
			}
			return result;
		}
		catch (const std::exception &e)
		{
			if (createdBranch && !createdBranchRoot.empty() && std::filesystem::exists(createdBranchRoot))
			{
				Log::error("Cleaning up incomplete branch: ", createdBranchRoot.string());
				std::filesystem::remove_all(createdBranchRoot);
			}
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
			// createCapture now returns the branch root (group/unfiltered)
			std::filesystem::path branchRoot = session.createCapture(type, captureName);
			std::filesystem::path rawDir = Session::getRawDir(branchRoot);

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
			Log::error("Error: calibrate requires calibration path (group root or branch root)");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		std::string capturePathArg = argv[2];
		std::string calibrationModel;
		std::string targetType;
		int cols = 0, rows = 0;
		float param3 = 0.0f, param4 = 0.0f;
		bool configProvided = false;

		for (int i = 3; i < argc; ++i) 
		{
			std::string arg = argv[i];
			if ((arg == "-t" || arg == "--target") && i + 1 < argc)
			{
				targetType = argv[++i];
			}
			else if (arg == "--model" && i + 1 < argc)
			{
				calibrationModel = argv[++i];
			}
			else if (arg == "--config" && i + 4 < argc)
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
			else
			{
				Log::error("Unknown calibrate option: ", arg);
				return EXIT_FAILURE;
			}
		}

		if (calibrationModel.empty())
		{
			Log::error("Error: calibrate requires --model <model>");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		if (!isSupportedModel(calibrationModel))
		{
			Log::error("Unknown model: ", calibrationModel, ". Supported models: e2vid, e2vidplus, e2vidplusupdate, firenet.");
			return EXIT_FAILURE;
		}

		try
		{
			std::filesystem::path inputPath = std::filesystem::absolute(capturePathArg);
			if (!std::filesystem::exists(inputPath))
			{
				Log::error("Error: Path does not exist: ", inputPath.string());
				return EXIT_FAILURE;
			}

			Session session = Session::load(Session::findSessionRoot(inputPath));
			std::filesystem::path branchRoot = session.resolveCalibrationBranchRoot(inputPath);
			std::string calibIdentifier = session.resolveCalibrationIdentifier(branchRoot);

			Log::info("Calibrating branch: ", branchRoot.string());
			Log::info("Calibration model: ", calibrationModel);

			std::filesystem::path framesDir = Session::getFramesModelDir(branchRoot, calibrationModel);
			std::filesystem::path configDir = session.getTargetsDir();

			if (!std::filesystem::exists(framesDir / "left") || !std::filesystem::exists(framesDir / "right"))
			{
				Log::error("Missing rendered frames for model '", calibrationModel, "' in ", framesDir.string());
				Log::error("Run 'sert render <path> --model ", calibrationModel, "' first.");
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

			if (Calib::createRosBag(branchRoot, calibrationModel) != EXIT_SUCCESS)
			{
				Log::error("Failed to create ROS bag for calibration.");
				return EXIT_FAILURE;
			}

			if (Calib::run(branchRoot, calibrationModel) != EXIT_SUCCESS)
			{
				Log::error("Calibration failed.");
				return EXIT_FAILURE;
			}

			try
			{
				if (!session.hasActiveCalibration())
				{
					session.setActiveCalibration(calibIdentifier, calibrationModel);
					Log::info("Calibration successful! Set '", calibIdentifier, "' [model: ", calibrationModel, "] as active calibration.");
				}
				else if (
					session.getActiveCalibration()->branch == calibIdentifier &&
					session.getActiveCalibration()->model == calibrationModel
				)
				{
					Log::info("Calibration successful! Active calibration remains '", calibIdentifier, "' [model: ", calibrationModel, "].");
				}
				else
				{
					const auto activeCalibration = session.getActiveCalibration().value();
					Log::info(
						"Calibration successful at '", calibIdentifier,
						"' [model: ", calibrationModel,
						"]. Active calibration remains '", activeCalibration.branch,
						"' [model: ", activeCalibration.model,
						"]. Use 'set-calibration --model <model>' to switch."
					);
				}
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
			Log::error("Error: set-calibration requires calibration path (group root or branch root)");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			std::string calibrationModel;
			for (int i = 3; i < argc; ++i)
			{
				std::string arg = argv[i];
				if (arg == "--model" && i + 1 < argc)
				{
					calibrationModel = argv[++i];
				}
				else
				{
					Log::error("Unknown set-calibration option: ", arg);
					return EXIT_FAILURE;
				}
			}

			if (calibrationModel.empty())
			{
				Log::error("Error: set-calibration requires --model <model>");
				logUsage(argv);
				return EXIT_FAILURE;
			}

			if (!isSupportedModel(calibrationModel))
			{
				Log::error("Unknown model: ", calibrationModel, ". Supported models: e2vid, e2vidplus, e2vidplusupdate, firenet.");
				return EXIT_FAILURE;
			}

			std::filesystem::path inputPath = std::filesystem::absolute(argv[2]);
			if (!std::filesystem::exists(inputPath))
			{
				Log::error("Error: Path does not exist: ", inputPath.string());
				return EXIT_FAILURE;
			}

			Session session = Session::load(Session::findSessionRoot(inputPath));
			std::string calibIdentifier = session.resolveCalibrationIdentifier(
				session.resolveCalibrationBranchRoot(inputPath)
			);
			session.setActiveCalibration(calibIdentifier, calibrationModel);
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

		"  render <path> [--model <model>] [--device <device>] [-- <e2vid_args...>]\n",
		"      Generate frames from events.\n",
		"      <path>     Group root or branch root (group root resolves to unfiltered)\n",
		"      --model    Reconstruction model: e2vid (default), e2vidplus, e2vidplusupdate, firenet\n",
		"      --device   Device to use: auto (default), cpu, xpu, cuda\n",
		"      --         Pass remaining args directly to backend scripts\n\n",

		"  filter <path> --config <path/to/config.yaml>\n",
		"      Create a filtered branch from the unfiltered branch\n",
		"      <path>     Group root or unfiltered branch root\n",
		"      Creates a sibling branch: filtered_<config_stem>/\n\n",

		"  calibrate <path> --model <model> [-t <target> --config <args>]\n",
		"      Run Kalibr calibration on a calibration branch\n",
		"      <path>     Calibration group root or branch root\n",
		"      --model    Render model to use: e2vid, e2vidplus, e2vidplusupdate, firenet\n",
		"      -t         Target type: aprilgrid, checkerboard, circlegrid\n",
		"      --config   Target config (required if no existing config):\n",
		"                   aprilgrid:    <cols> <rows> <tagSize> <tagSpacing>\n",
		"                   checkerboard: <cols> <rows> <rowSpacing> <colSpacing>\n",
		"                   circlegrid:   <cols> <rows> <spacing> <asymmetric 0/1>\n\n",

		"  set-calibration <path> --model <model>\n",
		"      Set active calibration for session\n",
		"      <path>     Calibration group root or branch root\n\n",

		"Examples:\n",
		"  ", cmd, " record -t calib                                       # Record calib in current session\n",
		"  ", cmd, " record lab -t scene -n scene_01                       # Create 'lab/' and record scene\n",
		"  ", cmd, " render lab/calibrations/calib_01                      # Render unfiltered branch\n",
		"  ", cmd, " render lab/scenes/scene_01/filtered_hot_only          # Render filtered branch\n",
		"  ", cmd, " filter lab/scenes/scene_01 --config lab/config/filters/hot_only.yaml\n",
		"  ", cmd, " calibrate lab/calibrations/calib_01 --model e2vid -t checkerboard --config 8 6 0.068 0.068\n",
		"  ", cmd, " set-calibration lab/calibrations/calib_01/unfiltered --model e2vid\n"
	);
}
