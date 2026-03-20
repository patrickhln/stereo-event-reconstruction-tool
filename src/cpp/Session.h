#pragma once
#include <filesystem>
#include <string>
#include <optional>

enum class CaptureType
{
	CALIBRATION,
	SCENE
};

class Session
{
public:
	static constexpr const char* UNFILTERED_BRANCH = "unfiltered";

	static Session create(const std::filesystem::path& parentPath, const std::string& name);
	static Session load(const std::filesystem::path& sessionPath);

	static bool isValidSession(const std::filesystem::path& path);
	static std::filesystem::path findSessionRoot(const std::filesystem::path& startPath);

	std::filesystem::path getPath() const { return rootPath_; }
	std::filesystem::path getConfigDir() const { return rootPath_ / "config"; }
	std::filesystem::path getTargetsDir() const { return rootPath_ / "config" / "targets"; }
	std::filesystem::path getCalibrationsDir() const { return rootPath_ / "calibrations"; }
	std::filesystem::path getScenesDir() const { return rootPath_ / "scenes"; }
	std::filesystem::path getLogsDir() const { return rootPath_ / "logs"; }

	std::string nextCalibrationName() const;
	std::string generateSceneName() const;

	// branch path helpers
	// given a config stem (e.g. "hot_only"), return "filtered_hot_only"
	static std::string filteredBranchName(const std::string& configStem);

	// check if a path is a branch root (has raw/ subdirectory)
	static bool isBranchRoot(const std::filesystem::path& path);

	// check if a path is a capture group root (has unfiltered/ subdirectory)
	static bool isGroupRoot(const std::filesystem::path& path);

	// resolve a path to a branch root:
	// - ff already a branch root, return it
	// - if a group root, resolve to unfiltered/ (prints resolution)
	// throws on failure.
	static std::filesystem::path resolveBranchRoot(const std::filesystem::path& path);
	std::filesystem::path resolveSceneBranchRoot(const std::filesystem::path& path) const;
	std::filesystem::path resolveCalibrationBranchRoot(const std::filesystem::path& path) const;

	// create capture group + unfiltered branch, returns the branch root
	std::filesystem::path createCapture(CaptureType type, const std::string& name = "");

	// detect capture type from an absolute path (checks if under calibrations/ or scenes/)
	CaptureType detectCaptureType(const std::filesystem::path& absolutePath) const;

	//branch-local directory accessors (work on any branch root)
	static std::filesystem::path getRawDir(const std::filesystem::path& branchRoot);
	static std::filesystem::path getIntermediateDir(const std::filesystem::path& branchRoot);
	static std::filesystem::path getFramesDir(const std::filesystem::path& branchRoot);
	static std::filesystem::path getReconstructionDir(const std::filesystem::path& branchRoot);
	static std::filesystem::path getEsvoDir(const std::filesystem::path& branchRoot);
	static std::filesystem::path getEsvo2Dir(const std::filesystem::path& branchRoot);
	static std::filesystem::path getRtabmapDir(const std::filesystem::path& branchRoot);

	// active calibration management (stores "group/branch" format, e.g. "calib_01/unfiltered")
	std::optional<std::string> getActiveCalibration() const;
	std::string resolveCalibrationIdentifier(const std::filesystem::path& path) const;
	void setActiveCalibration(const std::string& calibIdentifier);
	std::filesystem::path getActiveCamchainPath() const;
	bool hasActiveCalibration() const;

	void setCameraInfo(const std::string& leftCam, const std::string& rightCam);
	std::string getLeftCamera() const;
	std::string getRightCamera() const;

	std::string getName() const;

	// save session.yaml
	void save();

	// create internal branch directory structure (public for filter flow)
	static void createBranchDirs(const std::filesystem::path& branchRoot, CaptureType type);

private:
	Session() = default;
	void initializeDirectories();
	void loadConfig();
	std::filesystem::path resolveBranchRootInSubdir(
		const std::filesystem::path& path,
		const std::filesystem::path& subdirRoot,
		const std::string& kind) const;

	std::filesystem::path rootPath_;
	std::string name_;
	std::string created_;
	std::optional<std::string> activeCalibration_;
	std::string leftCamera_;
	std::string rightCamera_;
	std::string notes_;
};
