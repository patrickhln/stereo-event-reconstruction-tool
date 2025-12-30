# Prerequisites


OpenCV  
```bash
sudo apt install -y libopencv-dev
```


## Install E2VID (Reference / Manual Setup) [Optional]

> [!IMPORTANT]
> **Automated Installation**
>
> E2VID is included in this repository as a git submodule (`rpg_e2vid/`), pointing to a [fork](https://github.com/patrickhln/rpg_e2vid/tree/cpu-support) of [E2VID](https://github.com/uzh-rpg/rpg_e2vid).
>
> The steps below are handled **automatically** by `scripts/install_e2vid_env.sh` and **not required** for normal usage.
>
> The instructions here are provided primarily for reference and to document the underlying process.

The installation requires [Anaconda3](https://www.anaconda.com/download).
Minor adjustments were made to the code and installation requirements compared to the [original README](https://github.com/uzh-rpg/rpg_e2vid/blob/master/README.md) to ensure CPU compatibility.

### 1. Create the environment

```bash
conda create -n E2VID python=3.8
conda activate E2VID
```

### 2. Install Dependencies


```bash
conda install -y -c conda-forge pandas scipy opencv protobuf libprotobuf absl-py numpy=1.23.5
```

Since E2VID uses `np.int` which was deprecated in 1.20 and removed in 1.24 we
need to set numpy version explicitly

Now, for the pytorch installation, choose cpu only or cuda if available

```bash
conda install pytorch torchvision cudatoolkit=10.0 -c pytorch
```
or 
```bash
conda install pytorch torchvision cpuonly -c pytorch
```

### 3. Download model

Download the pretrained model:

```bash 
mkdir -p rpg_e2vid/pretrained
wget "http://rpg.ifi.uzh.ch/data/E2VID/models/E2VID_lightweight.pth.tar" -O rpg_e2vid/pretrained/E2VID_lightweight.pth.tar
```


## Third-party components

- **E2VID**: https://github.com/uzh-rpg/rpg_e2vid
    - Used via a fork (branch `cpu-support`) and included as a git submodule.
    - Fork: https://github.com/patrickhln/rpg_e2vid/tree/cpu-support
    - All original license information is preserved.
