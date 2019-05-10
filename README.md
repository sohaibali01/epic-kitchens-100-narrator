**Epic-annotator** is a tool written in Python to annotate actions in videos via narration. 

## Installation

Use conda with the provided environment to install the necessary dependencies:

```bash
conda env create -f environment.yml
```

Alternatively, you can try to install the necessary modules yourself:

- [GTK 3](https://www.gtk.org/)
- [python-vlc](https://pypi.org/project/python-vlc/)
- [pysoundfile](https://pypi.org/project/PySoundFile/)
  - This requires the `libsndfile` library to be installed in your system. 
    In Linux this should be available in all distributions. For Windows and MacOS 
    `pip install pysoundfile` should install the library automatically for you. 
- [pysounddevice](https://pypi.org/project/sounddevice/)
   - This requires [PortAudio](http://www.portaudio.com/) to be installed in your system. 
     In Linux this should be available in all distributions. For Windows and MacOS 
    `pip install sounddevice` should install the library automatically for you.
- [PyGObject](https://pypi.org/project/PyGObject/)
- [matplotlib](https://pypi.org/project/matplotlib/)

Note that the annotator works with Python 3 only. 

**Note also** that [VLC player](https://www.videolan.org/vlc/) must be installed in your system.

## Usage

Start the program with `python epic_narrator.py`. Once the program has started:

1. Make sure your microphone input is correctly being captured. You can do this by checking the signal
   displayed in the monitor level. If you don't see any signal as you speak try to select a different audio
   interface ([see below how](#Selecting-audio-interface)).
2. Load the video: `File -> Load video`
3. Choose where you want to save your recordings. The program will create the folders 
   `epic_annotator_recordings/video_name/` under your selected output folder.
4. Play the video and narrate actions 
 
### Playing and recording 

Use the playback buttons to pause/play the video, as well as seeking backwards and forwards and mute/unmute 
the video. 

You can use the slider to move across the  video. 

You can also change the speed of the playback.

To annotate an action press the microphone button. 
This will pause the video and will start recording your voice immediately. Once you have narrated the action, press 
the button again to stop the recording and continue annotating.

You will see all your recorded actions in the right hand-side panel. You can jump to the action location by clicking 
on the timestamp. You can also play and delete each recording with the corresponding buttons.

### Keyboard shortcuts

- `left arrow`: seek backwards
- `right arrow`: seek forwards
- `space bar`: pause/play video
- `enter`: start/stop recording
- `delete` or `backspace`: delete current recording (if pressed while recording) or the last recording in the video
- `m`: mute/unmute video
 
### Resume recording

To resume recording simply choose the same output folder you previously selected when you annotated the same video. 
This will automatically load all your recordings.

### Selecting audio device

Use the `Select microphone` menu to select the device you want to use. 
By default the program will use the first device listed in the menu.

In the unlikely case the program crashes at start time due to some issues with the audio interface, try to launch the
program as follows:
 
 ```bash
python epic_narrator.py --set_audio_device <device_id>
 ```
 
Run `python epic_narrator.py --query_audio_devices` to get the devices available in your system with their corresponding ids.

For example:

```bash
$ python epic_narrator.py --query_audio_devices
  0 HDA Intel PCH: ALC3220 Analog (hw:0,0), ALSA (2 in, 0 out)
< 1 HDA NVidia: HDMI 0 (hw:1,3), ALSA (0 in, 8 out)
  2 HDA NVidia: HDMI 1 (hw:1,7), ALSA (0 in, 8 out)
  3 DELL UZ2315H: USB Audio (hw:2,0), ALSA (2 in, 2 out)
  4 sysdefault, ALSA (128 in, 0 out)
> 5 default, ALSA (128 in, 0 out)
```

```bash
python epic_narrator.py --set_audio_device 3
```   

## Recordings

Recordings will be saved in mono uncompress format (`.wav`) sampled at the default sample rate of
your input audio interface.

