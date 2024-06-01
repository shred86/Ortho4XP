# Ortho4XP
A scenery generator for the X-Plane flight simulator.

NOTE 15/02/2024 : In transition to version 1.40.

Version 1.40 is mostly a compatibility update for XP 12 water requirements.
Some newer code related to 3D waterbed rendering is included, but one will have
to wait for XP 12.1 to potentially revise it. The default setting is XP11 (i.e. 
overlay based ) water rendering + bathymetry for 3D water and physics plane interaction. 
The new Ortho4XP tiles also automatically bring the seasons, sounds, etc raster from the
corresponding Global Scenery tiles.

The code as been updated to work with recent versions of the python modules it
depends on (you may have experienced some deprecation warnings or even some
code break due to Numpy, Pyproj and Shapely, these should be fixed with this
update). The only new python module used is skfmm (Fast Marching Method) and is only needed when using 
the distance_masks_too option, the program will run even without it.


TODO :
- Update install instructions (after user first tests). The ones included have
  not been updated at all, but the same list of decently recent python modules should 
  work out of the box.
- Check and update providers status.
- Compile nvcompress for OSX ARM64 (the included version is the old one renamed without the
  .app). A Linux version of nvcompress is included now because some distros are apparently 
  no longer shipping it. Triangle4XP has been updated for all OS, including ARM based Mac.
  I have not tested anything but Linux software.
- Incorporate some code changes that were in the old "devel" version (the
  present is an update from the v130 master branch only).
- Do something about the 3rd party initiatives to provide some Docker or other 
  Plug and Play versions.

## Installation

[Download](https://github.com/oscarpilote/Ortho4XP/archive/refs/heads/master.zip) this repository and extract it to a preferred location on your computer and follow the instructions for your operation system below.

### Windows

1. Download and install [Python 3.11.9](https://www.python.org/downloads/release/python-3119/). Use the "Customize installation" option and make sure "pip" and "tcl/tk and IDLE" are selected on the Optional Features page.

2. From a Command Prompt window, install the required packages:
```py -3.11 -m pip install -r requirements.txt```

3. Go to the Ortho4XP folder:
```cd /path/to/Ortho4XP```

4. Launch Ortho4XP:
```py -3.11 -m Ortho4XP_v130.py```

#### (Optional) Install tools needed for using elevation data (custom_dem) other than the default:

1. Download and install the latest [Microsoft Visual C++ Redistributable (Microsoft C and C++ (MSVC) runtime libraries)](https://aka.ms/vs/17/release/vc_redist.x86.exe). The link provided is specific for Windowws 64-bit (X86). If you need a different version, they can be found [here](https://learn.microsoft.com/en-US/cpp/windows/latest-supported-vc-redist?view=msvc-170#latest-microsoft-visual-c-redistributable-version).

2. Download the [Geospatial library wheels for Python](https://github.com/cgohlke/geospatial-wheels/releases/download/v2024.2.18/GDAL-3.8.4-cp311-cp311-win_amd64.whl). The link provided is specific for Python 3.11 and Windows 64-bit (X86). If you need a different version, they can be found [here](https://github.com/cgohlke/geospatial-wheels/releases).

3. Install GDAL (update the path to where you downloaded the file in step 2):
```py -3.11 -m "/path_to_downloaded_file_in_step_2/GDAL-3.8.4-cp311-cp311-win_amd64.whl"```

*Note: Window users should use Notepad++ or an equivalent editor to read and/or modify Ortho4XP related files. Notepad doesn't understand Linux line-ends and will create issues.*

### Linux 

#### Debian/Ubuntu-based distributions 

1. In a Terminal window, install the required packages:

``sudo apt-get install python3 python3-pip python3-requests python3-numpy python3-pyproj python3-gdal python3-shapely python3-rtree python3-pil python3-pil.imagetk p7zip-full libnvtt-bin freeglut3 gdal-bin```

2. Go to the Ortho4XP folder:
```cd /path/to/Ortho4XP```

3. Launch Ortho4XP:
```python3 Ortho4XP_v130.py```

#### Arch-based distributions

*Note: You must have the AUR enabled and yay installed.*

1. In a Terminal window, build and install the Nvidia Texture Tools:
```yay nvidia-texture-tools```

2. Install the required packages:
```sudo pacman -S python python-pip python-requests python-numpy python-pyproj python-gdal python-shapely python-rtree python-pillow python-pmw p7zip freeglut```

3. If some packages in step 2 are not available for your distro, you can use pip instead to install the missing Python packages. For example: 
```pip install pyproj```

*Note: Python module names may be different on other distributions.*

4. Launch Ortho4XP:
```python3 Ortho4XP_v130.py```

### macOS

1. In a Terminal window, install the [Homebrew package manager](https://brew.sh):
```/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"```

2. Install the required packages:
```brew install python@3.11 python-tk@3.11 spatialindex p7zip proj```

3. Install the required Python dependencies:
```pip3.11 install -r requirements.txt```

5. Go to the Ortho4XP folder:
```cd /path/to/Ortho4XP```

6. Allow macOS to run Ortho4XP tools:
```xattr -dr com.apple.quarantine ./Utils/mac/*```

7. Launch Ortho4XP:
```python3.11 Ortho4XP_v130.py```

#### (Optional) Install tools needed for using elevation data (custom_dem) other than the default:

1. Install the required packages:
```brew install gdal```

2. Install the gdal Python package:
```pip3.11 install gdal==$(gdal-config --version)```