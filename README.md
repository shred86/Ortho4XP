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

### Windows

*Note: Window users should use Notepad++ or an equivalent editor to read and/or modify Ortho4XP related files. Notepad doesn't understand Linux line-ends and will create issues.*

1) Download and install [Python 3.11.9](https://www.python.org/downloads/release/python-3119/). Make sure to that "pip" (package management system for Python)
is installed made accessible from your PATH. This is not not selected by default during the installation process.

2) Download the following packages from https://www.lfd.uci.edu/~gohlke/pythonlibs/

Pyproj, Numpy, Gdal, Shapely, Rtree, Pillow (or alternatively Pillow-SIMD)

Pay attention to take the ones that correspond to the Python version which you picked
at Step 1) and to your OS nbr of bits (32 or 64, I guess 64 in all but a few cases).
As an example, if Python 3.7.*  was selected at Step 1) above and you
have a 64bit windows, then you would choose these files that have -cp37- and _amd64 
within their filename.   

In order to use the build geotiff feature of the custom_zl map, you will need to 
add the directory containing gdal_translate and gdalwarp (***/python**/lib/site-packages/osgeo/) 
into your PATH variable.

Finally, if you do not already have them : download and install the build tools for visual studio (2017):
https://visualstudio.microsoft.com/fr/downloads/  

3) From a command window launch successively 

pip install --upgrade pip  [if this goes wrong you probably missed the last point in 1)]
pip install requests
pip install *******.whl [replacing ******** successively by each of the files downloaded at Step 2]

You should be done. Open a command window in the Ortho4XP directory (freshly downloaded from Github)
and launch "python Ortho4XP_v130.py".


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

3. Launch Ortho4XP:
```python3 Ortho4XP_v130.py```

### macOS

1. In a Terminal window, install the [Homebrew package manager](https://brew.sh):
```/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"```

2. Install the required packages:
```brew install python@3.11 python-tk@3.11 gdal spatialindex p7zip proj```

3. Install the required Python dependencies:
```pip3.11 install -r requirements.txt```

4. Go to the Ortho4XP folder:
```cd /path/to/Ortho4XP```

5. Launch Ortho4XP:
```python3.11 Ortho4XP_v130.py```
