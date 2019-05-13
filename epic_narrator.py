import os
import sys
import ctypes
import traceback
import argparse
import vlc
import numpy as np
import matplotlib
matplotlib.use('PS')
import matplotlib.pyplot as plt
import queue
import gi
from recorder import Recorder
from recordings import Recordings, ms_to_timestamp

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk, Pango
from matplotlib.animation import FuncAnimation
from matplotlib.backends.backend_gtk3agg import (FigureCanvasGTK3Agg as FigureCanvas)


if sys.platform.startswith('darwin'):
    plt.switch_backend('MacOSX')
else:
    plt.switch_backend('GTK3Agg')


class EpicAnnotator(Gtk.ApplicationWindow):
    def __init__(self, mic_device=0):
        Gtk.ApplicationWindow.__init__(self, title='Epic Annotator')

        self.video_length_ms = 0
        self.seek_step = 500  # 500ms
        self.red_tick_colour = "#ff3300"
        self.video_width = 600
        self.video_height = 400
        self.connect('destroy', Gtk.main_quit)
        self.recorder = Recorder(device_id=mic_device)
        self.recordings = None
        self.video_path = None
        self.is_video_loaded = False
        self.annotation_box_map = {}
        self.single_window = False if sys.platform.startswith('darwin') else True
        self.annotation_box_height = self.video_height if self.single_window else 200

        # menu
        self.file_menu = Gtk.Menu()
        self.load_video_menu_item = Gtk.MenuItem(label='Load video')
        self.file_menu.append(self.load_video_menu_item)
        self.file_menu_item = Gtk.MenuItem(label='File')
        self.file_menu_item.set_submenu(self.file_menu)
        self.menu_bar = Gtk.MenuBar()
        self.menu_bar.append(self.file_menu_item)
        self.load_video_menu_item.connect('button-press-event', self.choose_video)
        self.set_microphone_menu()

        # button icons
        self.seek_backward_image = Gtk.Image.new_from_icon_name('media-seek-backward', Gtk.IconSize.BUTTON)
        self.seek_forward_image = Gtk.Image.new_from_icon_name('media-seek-forward', Gtk.IconSize.BUTTON)
        self.play_image = Gtk.Image.new_from_icon_name('media-playback-start', Gtk.IconSize.BUTTON)
        self.pause_image = Gtk.Image.new_from_icon_name('media-playback-pause', Gtk.IconSize.BUTTON)
        self.mute_image = Gtk.Image.new_from_icon_name('audio-volume-muted', Gtk.IconSize.BUTTON)
        self.unmute_image = Gtk.Image.new_from_icon_name('audio-volume-high', Gtk.IconSize.BUTTON)
        self.mic_image = Gtk.Image.new_from_icon_name('audio-input-microphone', Gtk.IconSize.BUTTON)
        self.record_image = Gtk.Image.new_from_icon_name('media-record', Gtk.IconSize.BUTTON)

        # slider
        self.slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=None)
        self.slider.connect('change-value', self.slider_moved)
        self.slider.connect('button-press-event', self.slider_clicked)
        self.slider.connect('button-release-event', self.slider_released)
        self.slider.set_hexpand(True)
        self.slider.set_valign(Gtk.Align.CENTER)
        self.slider.set_draw_value(False)

        # buttons
        self.playback_button = Gtk.Button()
        self.record_button = Gtk.Button()
        self.mute_button = Gtk.Button()
        self.seek_backward_button = Gtk.Button()
        self.seek_forward_button = Gtk.Button()
        self.playback_button.set_image(self.play_image)
        self.record_button.set_image(self.mic_image)
        self.mute_button.set_image(self.unmute_image)
        self.seek_backward_button.set_image(self.seek_backward_image)
        self.seek_forward_button.set_image(self.seek_forward_image)
        self.seek_backward_button.connect('pressed', self.seek_backwards_pressed)
        self.seek_backward_button.connect('released', self.seek_backwards_released)
        self.seek_forward_button.connect('pressed', self.seek_forwards_pressed)
        self.seek_forward_button.connect('released', self.seek_forwards_released)
        self.playback_button.connect('clicked', self.toggle_player_playback)
        self.record_button.connect('clicked', self.toggle_record)
        self.mute_button.connect('clicked', self.toggle_audio)

        # video area
        self.video_area = Gtk.DrawingArea() if self.single_window else Gtk.Window(title='Epic Annotator')
        self.video_area.set_size_request(self.video_width, self.video_height)
        self.video_area.connect('realize', self.video_area_ready)

        # time label
        self.time_label = Gtk.Label()
        self.update_time_label(0)

        self.speed_time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # speed radio buttons
        speed_item = None
        self.normal_speed_button = None
        speeds = [0.50, 0.75, 1, 1.50, 2]

        self.speed_time_box.pack_start(Gtk.Label(label='Playback speed'), False, False, 10)

        for speed in speeds:
            speed_item = Gtk.RadioButton('{:0.2f}'.format(speed), group=speed_item)
            speed_item.connect('clicked', self.speed_selected, speed)

            if speed == 1:
                speed_item.set_active(True)
                self.normal_speed_button = speed_item

            self.speed_time_box.pack_start(speed_item, False, False, 0)

        self.speed_time_box.pack_end(self.time_label, False, False, 0)

        # button box
        self.button_box = Gtk.ButtonBox()
        self.button_box.pack_start(self.seek_backward_button, False, False, 0)
        self.button_box.pack_start(self.seek_forward_button, False, False, 0)
        self.button_box.pack_start(self.playback_button, False, False, 0)
        self.button_box.pack_start(self.record_button, False, False, 0)
        self.button_box.pack_start(self.mute_button, False, False, 0)
        self.button_box.set_spacing(10)
        self.button_box.set_layout(Gtk.ButtonBoxStyle.CENTER)

        # microphone monitor
        self.monitor_fig, self.monitor_ax, self.monitor_lines = self.recorder.prepare_monitor_fig()
        self.recorder_plot_data = np.zeros((self.recorder.length, len(self.recorder.channels)))
        canvas = FigureCanvas(self.monitor_fig)  # a Gtk.DrawingArea
        canvas.set_size_request(100, 50)
        self.monitor_label = Gtk.Label()
        self.set_monitor_label(False)
        self.monitor_animation = FuncAnimation(self.monitor_fig, self.update_mic_monitor,
                                               interval=self.recorder.plot_interval_ms, blit=True)

        # annotation box
        self.right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.annotation_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.annotation_scrolled_window = Gtk.ScrolledWindow()
        self.annotation_scrolled_window.set_border_width(10)
        self.annotation_scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.annotation_scrolled_window.add_with_viewport(self.annotation_box)
        self.right_box.pack_start(Gtk.Label('Recordings'), False, False, 10)
        self.right_box.pack_start(self.annotation_scrolled_window, True, True, 0)
        self.right_box.set_size_request(300, self.annotation_box_height)

        self.annotation_box.connect('size-allocate', self.scroll_annotations_to_bottom)

        self.video_path_label = Gtk.Label(label=' ')
        self.recordings_path_label = Gtk.Label(label=' ')

        # video box
        self.video_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.video_box.pack_start(self.menu_bar, False, False, 0)

        if self.single_window:
            self.video_box.pack_start(self.video_area, True, True, 0)
        else:
            self.video_area.show()
            self.video_area.move(0, 0)
            self.move(0, self.video_height+100)

            # enable only horizontal resize
            gh = Gdk.Geometry()
            gh.max_height = 300
            gh.min_height = 300
            gh.max_width = 2000
            gh.min_width = 700
            self.set_geometry_hints(None, gh, Gdk.WindowHints.MAX_SIZE)

        self.video_box.pack_start(self.speed_time_box, False, False, 10)
        self.video_box.pack_start(self.slider, False, False, 0)
        self.video_box.pack_start(self.button_box, False, False, 20)
        self.video_box.pack_start(self.monitor_label, False, False, 0)
        self.video_box.pack_start(canvas, False, False, 10)

        # bottom paths labels
        self.paths_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        for path_labels in [self.video_path_label, self.recordings_path_label]:
            path_labels.set_property('lines', 1)
            path_labels.set_ellipsize(Pango.EllipsizeMode.START)
            path_labels.set_property('max-width-chars', 50)

        video_path_placeholder = Gtk.Label()
        video_path_placeholder.set_markup('<span><b>Annotating video:</b></span>')
        recordings_path_placeholder = Gtk.Label()
        recordings_path_placeholder.set_markup('<span><b>Saving recordings to:</b></span>')
        self.paths_box.pack_start(video_path_placeholder, False, False, 10)
        self.paths_box.pack_start(self.video_path_label, False, False, 0)
        self.paths_box.pack_end(self.recordings_path_label, False, False, 0)
        self.paths_box.pack_end(recordings_path_placeholder, False, False, 10)

        self.video_box.pack_start(self.paths_box, False, False, 10)

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_box.pack_start(self.video_box, False, True, 0)
        self.main_box.pack_start(self.right_box, False, True, 0)

        self.add(self.main_box)

        # initial setup
        self.recorder.stream.start()  # starts the microphone stream
        self.toggle_media_controls(False)
        self.record_button.set_sensitive(False)
        self.mute_button.set_sensitive(False)

        settings = Gtk.Settings.get_default()
        settings.set_property("gtk-application-prefer-dark-theme", False)

        #self.set_position(Gtk.WindowPosition.MOUSE)

        self.connect("key-press-event", self.key_pressed)

    def set_monitor_label(self, is_recording):
        colour = '#ff3300' if is_recording else 'black'
        self.monitor_label.set_markup('<span foreground="{}">Microphone level</span>'.format(colour))

    def speed_selected(self, widget, speed):
        if self.is_video_loaded:
            self.player.set_rate(speed)

    def set_focus(self):
        widgets = [self.main_box, self.video_box, self.slider, self.button_box, self.video_box, self.button_box]

        for w in widgets:
            w.set_property('can-focus', False)

    def key_pressed(self, widget, event):
        if not self.is_video_loaded:
            return

        if event.keyval == Gdk.KEY_Left:
            self.seek_backwards()
        elif event.keyval == Gdk.KEY_Right:
            self.seek_forwards()
        elif event.keyval == Gdk.KEY_space:
            self.toggle_player_playback()
        elif event.keyval == Gdk.KEY_M or event.keyval == Gdk.KEY_m:
            self.toggle_audio()
        elif event.keyval == Gdk.KEY_Return:
            self.toggle_record()
        elif event.keyval == Gdk.KEY_Delete or event.keyval == Gdk.KEY_BackSpace:
            if self.recordings.empty():
                return

            if self.player.is_playing():
                paused = True
                self.pause_video()
            else:
                paused = False

            if self.recorder.is_recording:
                self.stop_recording(play_afterwards=paused)
                current_recording = True
            else:
                current_recording = False

            self.delete_last_recording(current_recording)

            if paused:
                self.play_video()
        else:
            return

    def show(self):
        self.show_all()

    def add_annotation_box(self, time_ms):
        box = Gtk.ButtonBox()

        time_button = Gtk.Button()
        time_label = Gtk.Label()
        time_label.set_markup('<span foreground="black"><tt>{}</tt></span>'.format(ms_to_timestamp(time_ms)))
        time_button.add(time_label)
        # time_label.show_all()

        a_play_button = Gtk.Button()
        # we need to create new images every time otherwise only the last entry will display the image
        a_play_button.set_image(Gtk.Image.new_from_icon_name('media-playback-start', Gtk.IconSize.BUTTON))
        a_delete_button = Gtk.Button()
        a_delete_button.set_image(Gtk.Image.new_from_icon_name('edit-delete', Gtk.IconSize.BUTTON))

        time_button.connect('button-press-event', self.go_to, time_ms)
        a_play_button.connect('button-press-event', self.play_recording, time_ms)
        a_delete_button.connect('button-press-event', self.delete_recording, time_ms)

        box.pack_start(time_button, False, False, 0)
        box.pack_start(a_play_button, False, False, 0)
        box.pack_start(a_delete_button, False, False, 0)
        box.set_layout(Gtk.ButtonBoxStyle.CENTER)
        box.set_spacing(5)
        box.show_all()

        self.annotation_box_map[time_ms] = box
        self.annotation_box.pack_start(box, False, True, 0)
        self.refresh_annotation_box()
        self.annotation_box.show_all()

    def go_to(self, widget, event, time_ms):
        self.slider.set_value(time_ms)
        self.player.set_time(int(time_ms))
        self.update_time_label(time_ms)

    def scroll_annotations_to_bottom(self, *args):
        adj = self.annotation_scrolled_window.get_vadjustment()
        adj.set_value(adj.get_upper())

    def play_recording(self, widget, event, time_ms):
        rec_player = vlc.Instance('--no-xlib').media_player_new()
        audio_media = self.vlc_instance.media_new_path(self.recordings.get_path_for_recording(time_ms))
        rec_player.set_mrl(audio_media.get_mrl())
        rec_player.audio_set_mute(False)
        rec_player.play()

    def delete_recording(self, widget, event, time_ms):
        dialog = Gtk.MessageDialog(self, 0, Gtk.MessageType.QUESTION,
                                   (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK),
                                    'Confirm delete')
        dialog.format_secondary_text('Are you sure you want to delete recording at time {}?'.format(
            ms_to_timestamp(time_ms)))
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            self.recordings.delete_recording(time_ms)
            self.remove_annotation_box(widget.get_parent())
            self.refresh_recording_ticks()

    def delete_last_recording(self, current_recording):
        if current_recording:
            msg = 'Are you sure you want to delete this recording?'
        else:
            time_ms = self.recordings.get_last_recording_time()
            msg = 'Are you sure you want to delete recording at time {}?'.format(ms_to_timestamp(time_ms))

        dialog = Gtk.MessageDialog(self, 0, Gtk.MessageType.QUESTION,
                                   (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK),
                                   'Confirm delete')
        dialog.format_secondary_text(msg)
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            children = self.annotation_box.get_children()
            self.recordings.delete_last()
            self.remove_annotation_box(children[-1])
            self.refresh_recording_ticks()
            return True
        else:
            return False

    def remove_annotation_box(self, widget):
        self.annotation_box_map = {key: val for key, val in self.annotation_box_map.items() if val != widget}
        self.annotation_box.remove(widget)
        self.refresh_annotation_box()

    def remove_all_annotation_boxes(self):
        for w in self.annotation_box.get_children():
            self.annotation_box.remove(w)

    def refresh_annotation_box(self):
        order = sorted(list(self.annotation_box_map.keys()))

        for time_ms, widget in self.annotation_box_map.items():
            position = order.index(time_ms)
            self.annotation_box.reorder_child(widget, position)

    def add_time_tick(self, time_ms, colour=None):
        self.slider.add_mark(time_ms, Gtk.PositionType.TOP, None)

    def add_start_end_slider_ticks(self):
        self.add_time_tick(1)
        self.add_time_tick(self.video_length_ms)

    def refresh_recording_ticks(self):
        self.slider.clear_marks()

        for time_ms in self.recordings.get_recordings_times():
            self.add_time_tick(time_ms, colour=self.red_tick_colour)

    def set_microphone_menu(self):
        devices = Recorder.get_devices()
        self.mic_menu = Gtk.Menu()
        self.mic_menu_item = Gtk.MenuItem('Select microphone')
        self.mic_menu_item.set_submenu(self.mic_menu)

        mic_item = None

        for dev_idx, dev in enumerate(devices):
            dev_name = dev['name']

            mic_item = Gtk.RadioMenuItem(dev_name, group=mic_item)
            mic_item.connect('activate', self.microphone_selected, dev_idx)

            if dev_idx == self.recorder.device_id:
                mic_item.set_active(True)

            self.mic_menu.append(mic_item)

        self.menu_bar.append(self.mic_menu_item)

    def microphone_selected(self, mic_item, index):
        try:
            self.recorder.change_device(index)
            self.recorder.stream.start()  # starts the microphone stream
        except Exception as e:
            traceback.print_exc()
            dialog = Gtk.MessageDialog(self, 0, Gtk.MessageType.ERROR, Gtk.ButtonsType.OK, 'Cannot use this device')
            dialog.format_secondary_text('Please select another device and check you can see a signal in the '
                                         'microphone level when you speak')
            dialog.run()
            dialog.destroy()

    def choose_video(self, *args):
        if self.is_video_loaded:
            confirm_dialog = Gtk.MessageDialog(self, 0, Gtk.MessageType.QUESTION,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK),
                                       'Confirm loading another video')
            confirm_dialog.format_secondary_text('Are you sure you want to load another video?')
            response = confirm_dialog.run()

            if response != Gtk.ResponseType.OK:
                confirm_dialog.destroy()
                return

            confirm_dialog.destroy()

        dialog = Gtk.FileChooserDialog("Open video", self, action=Gtk.FileChooserAction.OPEN,
                                    buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        file_filter = Gtk.FileFilter()
        file_filter.set_name("Video files")
        file_filter.add_mime_type("video/*")
        dialog.add_filter(file_filter)

        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            self.setup(path)

        dialog.destroy()

    def update_mic_monitor(self, *args):
        while True:
            try:
                data = self.recorder.q.get_nowait()
            except queue.Empty:
                break

            shift = len(data)
            self.recorder_plot_data = np.roll(self.recorder_plot_data, -shift, axis=0)
            self.recorder_plot_data[-shift:, :] = data

        for column, line in enumerate(self.monitor_lines):
            line.set_ydata(self.recorder_plot_data[:, column])
            color = 'red' if self.recorder.is_recording else 'white'
            line.set_color(color)

        return self.monitor_lines

    def toggle_record(self, *args):
        if not self.recorder.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def stop_recording(self, play_afterwards=True):
        self.recorder.stop_recording()
        self.record_button.set_image(self.mic_image)
        self.set_monitor_label(False)
        self.toggle_media_controls(True)

        if play_afterwards:
            self.play_video(None)

    def start_recording(self):
        self.record_button.set_image(self.record_image)
        self.set_monitor_label(True)
        self.toggle_media_controls(False)

        if self.player.is_playing():
            self.pause_video(None)

        rec_time = self.player.get_time()
        path = self.recordings.add_recording(rec_time)
        self.recorder.start_recording(path)
        self.add_annotation_box(rec_time)
        self.add_time_tick(rec_time, colour=self.red_tick_colour)

    def toggle_media_controls(self, active):
        self.slider.set_sensitive(active)
        self.seek_backward_button.set_sensitive(active)
        self.seek_forward_button.set_sensitive(active)
        self.playback_button.set_sensitive(active)

    def seek_backwards_pressed(self, *args):
        # there is no hold event in Gtk apparently, so we need to do this
        self._timeout_id_backwards = GLib.timeout_add(50, self.seek_backwards)

    def seek_backwards_released(self, *args):
        # remove timeout
        GLib.source_remove(self._timeout_id_backwards)
        self._timeout_id_backwards = 0

    def seek_backwards(self):
        seek_pos = self.slider.get_value() - self.seek_step

        if seek_pos >= 1:
            self.player.set_time(int(seek_pos))
            self.video_moving(None)

        return True  # this will be called inside a timeout so we return True

    def seek_forwards_pressed(self, *args):
        # there is no hold event in Gtk apparently, so we need to do this
        timeout = 50
        self._timeout_id_forwards = GLib.timeout_add(timeout, self.seek_forwards)

    def seek_forwards_released(self, *args):
        # remove timeout
        GLib.source_remove(self._timeout_id_forwards)
        self._timeout_id_forwards = 0

    def seek_forwards(self):
        seek_pos = self.slider.get_value() + self.seek_step

        if seek_pos < self.video_length_ms:
            self.player.set_time(int(seek_pos))
            self.video_moving(None)

        return True  # this will be called inside a timeout so we return True

    def slider_clicked(self, *args):
        pass  # no need to do anything

    def slider_released(self, *args):
        slider_pos_ms = int(self.slider.get_value())
        self.player.set_time(slider_pos_ms)

    def pause_video(self, *args):
        self.player.pause()
        self.playback_button.set_image(self.play_image)

    def play_video(self, *args):
        self.player.play()
        self.playback_button.set_image(self.pause_image)

    def toggle_player_playback(self, *args):
        if self.player.is_playing():
            self.pause_video(args)
        else:
            self.player.play()
            self.play_video(args)

    def toggle_audio(self, *args):
        if self.player.audio_get_mute():
            self.mute_button.set_image(self.mute_image)
            self.player.audio_set_mute(False)
        else:
            self.mute_button.set_image(self.unmute_image)
            self.player.audio_set_mute(True)

    def update_time_label(self, ms):
        ms_str = ms_to_timestamp(ms)
        total_length_str = ms_to_timestamp(self.video_length_ms)
        time_txt = ' {} / {} '.format(ms_str, total_length_str)
        self.time_label.set_markup('<span bgcolor="black" fgcolor="white"><tt>{}</tt></span>'.format(time_txt))

    def video_loaded(self, *args):
        # we need to play the video for a while to get the length in milliseconds,
        # so this will be called at the beginning
        self.video_length_ms = self.player.get_length()

        if self.video_length_ms > 0:
            self.slider.set_range(1, self.video_length_ms)
            # self.add_start_end_slider_ticks()
            return False  # video has loaded, will not call this again
        else:
            return True  # video not loaded yet, will try again later

    def video_moving(self, *args):
        current_time_ms = self.player.get_time()
        self.slider.set_value(current_time_ms)
        self.update_time_label(current_time_ms)

    def slider_moved(self, *args):
        # this is called when is moved by the user
        if self.video_length_ms == 0:
            return False  # just to make sure we don't move the slider before we get the video duration

        slider_pos_ms = self.slider.get_value()
        self.player.set_time(int(slider_pos_ms))
        self.update_time_label(slider_pos_ms)

        return False

    def video_ended(self, data):
        GLib.timeout_add(100, self.reload_current_video)  # need to call this with some delay otherwise it gets stuck

    def reload_current_video(self):
        self.player.set_media(self.player.get_media())
        self.slider.set_value(1)
        self.pause_video(None)
        return False  # return False so we stop this timer

    def set_vlc_window(self):
        if sys.platform.startswith('linux'):
            win_id = self.video_area.get_window().get_xid()
            self.player.set_xwindow(win_id)
        elif sys.platform.startswith('darwin'):
            # ugly bit to get window if on mac os
            window = self.video_area.get_property('window')
            ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
            ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object]
            gpointer = ctypes.pythonapi.PyCapsule_GetPointer(window.__gpointer__, None)
            libgdk = ctypes.CDLL("libgdk-3.dylib")
            libgdk.gdk_quartz_window_get_nsview.restype = ctypes.c_void_p
            libgdk.gdk_quartz_window_get_nsview.argtypes = [ctypes.c_void_p]
            handle = libgdk.gdk_quartz_window_get_nsview(gpointer)
            self.player.set_nsobject(int(handle))

    def setup_vlc_player(self, widget):
        self.vlc_instance = vlc.Instance('--no-xlib')
        self.player = self.vlc_instance.media_player_new()
        self.set_vlc_window()
        events = self.player.event_manager()
        events.event_attach(vlc.EventType.MediaPlayerPositionChanged, self.video_moving)
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self.video_ended)

    def video_area_ready(self, widget):
        self.setup_vlc_player(widget)

    def choose_output_folder(self, default_output):
        dialog = Gtk.FileChooserDialog("Select output folder", self, action=Gtk.FileChooserAction.SELECT_FOLDER,
                                    buttons=(Gtk.STOCK_OK, Gtk.ResponseType.OK))

        dialog.set_current_folder(default_output)
        dialog.run()
        path = dialog.get_filename()
        dialog.destroy()

        return path

    def set_video_recordings_paths_labels(self):
        self.video_path_label.set_text(self.video_path)
        self.recordings_path_label.set_text(self.recordings.video_annotations_folder)


    def setup(self, video_path):
        self.video_path = video_path
        media = self.vlc_instance.media_new_path(self.video_path)
        self.player.set_mrl(media.get_mrl())

        self.playback_button.set_image(self.pause_image)
        self.player.audio_set_mute(True)
        self.toggle_media_controls(True)
        self.record_button.set_sensitive(True)
        self.mute_button.set_sensitive(True)
        self.is_video_loaded = True

        output_path = self.choose_output_folder(os.path.join(os.path.expanduser("~")))

        if self.recordings is not None:
            # reset things
            self.slider.clear_marks()
            self.remove_all_annotation_boxes()
            self.annotation_box_map = {}
            del self.recordings

        self.recordings = Recordings(output_path, self.video_path)

        GLib.timeout_add(50, self.video_loaded)  # we need to play the video to get the time

        if self.recordings.annotations_exist():
            self.recordings.load_annotations()

            for rec_ms in self.recordings.get_recordings_times():
                self.add_annotation_box(rec_ms)
                self.add_time_tick(rec_ms, colour=self.red_tick_colour)

        self.normal_speed_button.set_active(True)  # reset normal speed
        self.set_video_recordings_paths_labels()
        self.play_video()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--query_audio_devices', action='store_true',
                        help='Print the audio devices available in your system')
    parser.add_argument('--set_audio_device', type=int, default=0,
                        help='Set audio device to be used for recording, given the device id. '
                             'Use `--query_audio_devices` to get the devices available in your system with their '
                             'corresponding ids')

    args = parser.parse_args()

    if args.query_audio_devices:
        print(Recorder.get_devices())
        exit()

    annotator = EpicAnnotator(mic_device=args.set_audio_device)
    annotator.show()
    Gtk.main()
    annotator.player.stop()
    annotator.vlc_instance.release()
