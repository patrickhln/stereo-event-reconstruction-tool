#include "Session.h"
#include "Log.h"

#include <yaml-cpp/yaml.h>
#include <fstream>
#include <chrono>
#include <iomanip>
#include <sstream>
#include <regex>

// example: 2026-02-02_13-01-01
static std::string getCurrentTimestamp()
{
	auto now = std::chrono::system_clock::now();
	auto in_time_t = std::chrono::system_clock::to_time_t(now);
	std::stringstream ss;
	ss << std::put_time(std::localtime(&in_time_t), "%Y-%m-%d_%H-%M-%S");
	return ss.str();
}
// example (uses T seperator) 2026-02-02T13:01:01Z
static std::string getISOTimestamp()
{
	auto now = std::chrono::system_clock::now();
	auto in_time_t = std::chrono::system_clock::to_time_t(now);
	std::stringstream ss;
	ss << std::put_time(std::gmtime(&in_time_t), "%Y-%m-%dT%H:%M:%SZ");
	return ss.str();
}

static void writeFileIfMissing(const std::filesystem::path &path, const std::string &content)
{
	if (std::filesystem::exists(path))
	{
		return;
	}

	std::ofstream file(path);
	if (!file.is_open())
	{
		throw std::runtime_error("Could not create file: " + path.string());
	}
	file << content;
}

static bool isWithinDirectory(const std::filesystem::path& child, const std::filesystem::path& parent)
{
	std::filesystem::path rel = child.lexically_relative(parent);
	return !rel.empty() && *rel.begin() != "..";
}

Session Session::create(const std::filesystem::path& parentPath, const std::string& name)
{
	Session session;

	std::string sessionName = name.empty() ? getCurrentTimestamp() : name;
	session.rootPath_ = parentPath / sessionName;
	session.name_ = sessionName;
	session.created_ = getISOTimestamp();
	session.activeCalibration_ = std::nullopt;

	session.initializeDirectories();
	session.save();

	Log::info("Created session: ", session.rootPath_.string());
	return session;
}

Session Session::load(const std::filesystem::path& sessionPath)
{
	Session session;
	session.rootPath_ = sessionPath;

	if (!isValidSession(sessionPath))
	{
		throw std::runtime_error("Invalid session path: " + sessionPath.string());
	}

	session.loadConfig();
	return session;
}

bool Session::isValidSession(const std::filesystem::path& path)
{
	// maybe make sure session.yaml also contains certain keywords
	return std::filesystem::exists(path / "session.yaml");
}

std::filesystem::path Session::findSessionRoot(const std::filesystem::path& startPath)
{
	std::filesystem::path current = std::filesystem::absolute(startPath);
	if (std::filesystem::is_regular_file(current))
		current = current.parent_path();

	while (!current.empty())
	{
		if (isValidSession(current))
			return current;
		auto parent = current.parent_path();
		if (parent == current) break;
		current = parent;
	}
	throw std::runtime_error("No session found in path hierarchy: " + startPath.string());
}

void Session::initializeDirectories()
{
	std::filesystem::create_directories(rootPath_);
	std::filesystem::create_directories(getConfigDir());
	std::filesystem::create_directories(getTargetsDir());
	std::filesystem::path filtersDir = getConfigDir() / "filters";
	std::filesystem::create_directories(filtersDir);
	std::filesystem::create_directories(getCalibrationsDir());
	std::filesystem::create_directories(getScenesDir());

	writeFileIfMissing(filtersDir / "hot_only.yaml", R"(chain:
  - type: hot_pixel

hot_pixel:
  auto_detect: true
  n_std_dev: 4.0
  n_hot_pixels: -1
)");

	writeFileIfMissing(filtersDir / "ba_only.yaml", R"(chain:
  - type: background_activity
    time_window_us: 3000
)");

	writeFileIfMissing(filtersDir / "hot_then_ba.yaml", R"(chain:
  - type: hot_pixel
  - type: background_activity
    time_window_us: 3000

hot_pixel:
  auto_detect: true
  n_std_dev: 4.0
  n_hot_pixels: -1
)");

	writeFileIfMissing(filtersDir / "ba_then_hot.yaml", R"(chain:
  - type: background_activity
    time_window_us: 3000
  - type: hot_pixel

hot_pixel:
  auto_detect: true
  n_std_dev: 4.0
  n_hot_pixels: -1
)");

	// logs/ created on-demand when logging is implemented
}

void Session::loadConfig()
{
	std::filesystem::path configPath = rootPath_ / "session.yaml";

	try
	{
		YAML::Node config = YAML::LoadFile(configPath.string());

		name_ = config["name"].as<std::string>("");
		created_ = config["created"].as<std::string>("");

		if (config["active_calibration"] && !config["active_calibration"].IsNull())
		{
			YAML::Node activeCalibration = config["active_calibration"];
			activeCalibration_ = ActiveCalibrationSelection{
				activeCalibration["branch"].as<std::string>(),
				activeCalibration["model"].as<std::string>()
			};
		}

		if (config["cameras"])
		{
			leftCamera_ = config["cameras"]["left"].as<std::string>("");
			rightCamera_ = config["cameras"]["right"].as<std::string>("");
		}

		notes_ = config["notes"].as<std::string>("");
	}
	catch (const YAML::Exception& e)
	{
		throw std::runtime_error("Failed to load session.yaml: " + std::string(e.what()));
	}
}

void Session::save()
{
	YAML::Emitter out;
	out << YAML::BeginMap;
	out << YAML::Key << "name" << YAML::Value << name_;
	out << YAML::Key << "created" << YAML::Value << created_;

	if (activeCalibration_.has_value())
	{
		out << YAML::Key << "active_calibration" << YAML::Value << YAML::BeginMap;
		out << YAML::Key << "branch" << YAML::Value << activeCalibration_->branch;
		out << YAML::Key << "model" << YAML::Value << activeCalibration_->model;
		out << YAML::EndMap;
	}
	else
	{
		out << YAML::Key << "active_calibration" << YAML::Value << YAML::Null;
	}

	out << YAML::Key << "cameras" << YAML::Value << YAML::BeginMap;
	out << YAML::Key << "left" << YAML::Value << leftCamera_;
	out << YAML::Key << "right" << YAML::Value << rightCamera_;
	out << YAML::EndMap;

	out << YAML::Key << "notes" << YAML::Value << notes_;
	out << YAML::EndMap;

	std::filesystem::path configPath = rootPath_ / "session.yaml";
	std::ofstream fout(configPath);
	fout << out.c_str();
	fout.close();
}

std::string Session::nextCalibrationName() const
{
	int maxNum = 0;
	std::regex calibPattern("calib_(\\d+)");

	if (std::filesystem::exists(getCalibrationsDir()))
	{
		for (const auto& entry : std::filesystem::directory_iterator(getCalibrationsDir()))
		{
			if (entry.is_directory())
			{
				std::string dirName = entry.path().filename().string();
				std::smatch match;
				if (std::regex_match(dirName, match, calibPattern))
				{
					int num = std::stoi(match[1].str());
					if (num > maxNum) maxNum = num;
				}
			}
		}
	}

	std::stringstream ss;
	ss << "calib_" << std::setfill('0') << std::setw(2) << (maxNum + 1);
	return ss.str();
}

std::string Session::generateSceneName() const
{
	return "scene_" + getCurrentTimestamp();
}

// --- Branch-aware helpers ---

std::string Session::filteredBranchName(const std::string& configStem)
{
	return "filtered_" + configStem;
}

bool Session::isBranchRoot(const std::filesystem::path& path)
{
	return std::filesystem::exists(path) && std::filesystem::is_directory(path)
		&& std::filesystem::exists(path / "raw");
}

bool Session::isGroupRoot(const std::filesystem::path& path)
{
	return std::filesystem::exists(path) && std::filesystem::is_directory(path)
		&& std::filesystem::exists(path / UNFILTERED_BRANCH);
}

std::filesystem::path Session::resolveBranchRoot(const std::filesystem::path& path)
{
	std::filesystem::path absPath = std::filesystem::absolute(path);

	// Already a branch root (has raw/ inside)
	if (isBranchRoot(absPath))
	{
		return absPath;
	}

	// Group root with unfiltered/ branch
	if (isGroupRoot(absPath))
	{
		std::filesystem::path branchRoot = absPath / UNFILTERED_BRANCH;
		Log::info("Resolved group root to branch: ", branchRoot.string());
		return branchRoot;
	}

	throw std::runtime_error(
		"Cannot resolve branch root from: " + absPath.string() + "\n"
		"Expected either a branch root (containing raw/) or a group root (containing unfiltered/)."
	);
}

std::filesystem::path Session::resolveBranchRootInSubdir(
	const std::filesystem::path& path,
	const std::filesystem::path& subdirRoot,
	const std::string& kind) const
{
	std::filesystem::path branchRoot = std::filesystem::weakly_canonical(resolveBranchRoot(path));
	std::filesystem::path canonicalSubdirRoot = std::filesystem::weakly_canonical(subdirRoot);

	if (!isWithinDirectory(branchRoot, canonicalSubdirRoot))
	{
		throw std::runtime_error("Path is not a " + kind + " branch under this session: " + branchRoot.string());
	}

	return branchRoot;
}

std::filesystem::path Session::resolveSceneBranchRoot(const std::filesystem::path& path) const
{
	return resolveBranchRootInSubdir(path, getScenesDir(), "scene");
}

std::filesystem::path Session::resolveCalibrationBranchRoot(const std::filesystem::path& path) const
{
	return resolveBranchRootInSubdir(path, getCalibrationsDir(), "calibration");
}

CaptureType Session::detectCaptureType(const std::filesystem::path& absolutePath) const
{
	std::filesystem::path branchRoot = std::filesystem::weakly_canonical(resolveBranchRoot(absolutePath));
	if (isWithinDirectory(branchRoot, std::filesystem::weakly_canonical(getCalibrationsDir())))
	{
		return CaptureType::CALIBRATION;
	}
	if (isWithinDirectory(branchRoot, std::filesystem::weakly_canonical(getScenesDir())))
	{
		return CaptureType::SCENE;
	}

	throw std::runtime_error("Cannot determine capture type for: " + branchRoot.string()
		+ "\nPath must be under calibrations/ or scenes/ within the session.");
}

void Session::createBranchDirs(const std::filesystem::path& branchRoot, CaptureType type)
{
	std::filesystem::create_directories(getRawDir(branchRoot));
	std::filesystem::create_directories(getIntermediateDir(branchRoot));
	std::filesystem::create_directories(getFramesDir(branchRoot));

	if (type == CaptureType::CALIBRATION)
	{
		std::filesystem::create_directories(getCalibrationArtifactsDir(branchRoot));
	}
	else if (type == CaptureType::SCENE)
	{
		std::filesystem::create_directories(getReconstructionDir(branchRoot));
	}
}

std::filesystem::path Session::createCapture(CaptureType type, const std::string& name)
{
	std::filesystem::path groupRoot;
	std::string captureName;

	if (type == CaptureType::CALIBRATION)
	{
		captureName = name.empty() ? nextCalibrationName() : name;
		groupRoot = getCalibrationsDir() / captureName;
	}
	else
	{
		captureName = name.empty() ? generateSceneName() : name;
		groupRoot = getScenesDir() / captureName;
	}

	std::filesystem::path branchRoot = groupRoot / UNFILTERED_BRANCH;
	createBranchDirs(branchRoot, type);

	Log::info("Created capture group: ", groupRoot.string());
	Log::info("Created branch: ", branchRoot.string());
	return branchRoot;
}

std::filesystem::path Session::getRawDir(const std::filesystem::path& branchRoot)
{
	return branchRoot / "raw";
}

std::filesystem::path Session::getIntermediateDir(const std::filesystem::path& branchRoot)
{
	return branchRoot / "intermediate";
}

std::filesystem::path Session::getFramesDir(const std::filesystem::path& branchRoot)
{
	return branchRoot / "frames";
}

std::filesystem::path Session::getFramesModelDir(const std::filesystem::path& branchRoot, const std::string& model)
{
	return getFramesDir(branchRoot) / model;
}

std::filesystem::path Session::getCalibrationArtifactsDir(const std::filesystem::path& branchRoot)
{
	return branchRoot / "calibration";
}

std::filesystem::path Session::getCalibrationModelDir(const std::filesystem::path& branchRoot, const std::string& model)
{
	return getCalibrationArtifactsDir(branchRoot) / model;
}

std::filesystem::path Session::getCalibrationCamchainPath(const std::filesystem::path& branchRoot, const std::string& model)
{
	return getCalibrationModelDir(branchRoot, model) / "stereo_frames-camchain.yaml";
}

std::filesystem::path Session::getCalibrationReportPath(const std::filesystem::path& branchRoot, const std::string& model)
{
	return getCalibrationModelDir(branchRoot, model) / "stereo_frames-report-cam.pdf";
}

std::filesystem::path Session::getCalibrationResultsPath(const std::filesystem::path& branchRoot, const std::string& model)
{
	return getCalibrationModelDir(branchRoot, model) / "stereo_frames-results-cam.txt";
}

std::filesystem::path Session::getCalibrationImuCamchainPath(const std::filesystem::path& branchRoot, const std::string& model)
{
	return getCalibrationModelDir(branchRoot, model) / "stereo_frames-camchain-imucam.yaml";
}

std::filesystem::path Session::getCalibrationImuReportPath(const std::filesystem::path& branchRoot, const std::string& model)
{
	return getCalibrationModelDir(branchRoot, model) / "stereo_frames-report-imucam.pdf";
}

std::filesystem::path Session::getCalibrationImuResultsPath(const std::filesystem::path& branchRoot, const std::string& model)
{
	return getCalibrationModelDir(branchRoot, model) / "stereo_frames-results-imucam.txt";
}

std::filesystem::path Session::getReconstructionDir(const std::filesystem::path& branchRoot)
{
	return branchRoot / "reconstruction";
}

std::filesystem::path Session::getEsvoDir(const std::filesystem::path& branchRoot)
{
	return branchRoot / "reconstruction" / "esvo";
}

std::filesystem::path Session::getEsvo2Dir(const std::filesystem::path& branchRoot)
{
	return branchRoot / "reconstruction" / "esvo2";
}

std::filesystem::path Session::getRtabmapDir(const std::filesystem::path& branchRoot)
{
	return branchRoot / "reconstruction" / "rtabmap";
}

std::optional<ActiveCalibrationSelection> Session::getActiveCalibration() const
{
	return activeCalibration_;
}

std::string Session::resolveCalibrationIdentifier(const std::filesystem::path& path) const
{
	std::filesystem::path branchRoot = resolveCalibrationBranchRoot(path);
	std::filesystem::path calibrationsDir = std::filesystem::weakly_canonical(getCalibrationsDir());
	return std::filesystem::relative(branchRoot, calibrationsDir).generic_string();
}

void Session::setActiveCalibration(const std::string& calibIdentifier, const std::string& model)
{
	std::filesystem::path calibBranchDir = resolveCalibrationBranchRoot(getCalibrationsDir() / calibIdentifier);
	std::string canonicalIdentifier = std::filesystem::relative(
		calibBranchDir,
		std::filesystem::weakly_canonical(getCalibrationsDir())
	).generic_string();

	if (!std::filesystem::exists(calibBranchDir))
	{
		throw std::runtime_error("Calibration branch does not exist: " + calibBranchDir.string());
	}
	if (!std::filesystem::exists(getCalibrationCamchainPath(calibBranchDir, model)))
	{
		throw std::runtime_error(
			"Calibration has no camchain file for model '" + model + "': " + canonicalIdentifier
		);
	}

	activeCalibration_ = ActiveCalibrationSelection{canonicalIdentifier, model};
	save();

	Log::info("Set active calibration to: ", canonicalIdentifier, " [model: ", model, "]");
}

std::filesystem::path Session::getActiveCamchainPath() const
{
	if (!activeCalibration_.has_value())
	{
		throw std::runtime_error("No active calibration set");
	}
	std::filesystem::path calibDir = resolveCalibrationBranchRoot(getCalibrationsDir() / activeCalibration_->branch);
	std::string canonicalIdentifier = std::filesystem::relative(
		calibDir,
		std::filesystem::weakly_canonical(getCalibrationsDir())
	).generic_string();
	std::filesystem::path camchainPath = getCalibrationCamchainPath(calibDir, activeCalibration_->model);
	if (std::filesystem::exists(camchainPath))
	{
		return camchainPath;
	}
	throw std::runtime_error(
		"Active calibration has no camchain file for model '" + activeCalibration_->model + "': " + canonicalIdentifier
	);
}

bool Session::hasActiveCalibration() const
{
	return activeCalibration_.has_value();
}

void Session::setCameraInfo(const std::string& leftCam, const std::string& rightCam)
{
	leftCamera_ = leftCam;
	rightCamera_ = rightCam;
	save();
}

std::string Session::getLeftCamera() const
{
	return leftCamera_;
}

std::string Session::getRightCamera() const
{
	return rightCamera_;
}

std::string Session::getName() const
{
	return name_;
}
