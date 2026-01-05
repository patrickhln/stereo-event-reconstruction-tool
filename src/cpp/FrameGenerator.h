#pragma once
#include <filesystem>
#include <string>

namespace FrameGen
{
	struct CameraMetadata
	{
		std::string leftCamName, rightCamName;
	};
	int environment_installed(); 
	int convertAedat4ToTxt(const std::filesystem::path& inputAedat4, const std::filesystem::path& outputDir, const std::string& leftCamName, const std::string& rightCamName); 
	int runE2VID(const std::filesystem::path& eventFile, const std::filesystem::path& outputDir, const std::string& datasetName);
	int recordingToVideo(const std::filesystem::path& intermediateDir, const std::filesystem::path& reconstructionDir);
	CameraMetadata readMetadata(const std::filesystem::path& directory);
	
}
