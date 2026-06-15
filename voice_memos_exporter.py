import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sqlite3
import os
import shutil
from datetime import datetime, timedelta
import re
import subprocess
import sys
import json
import shlex
import plistlib
import tempfile
import threading
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

APP_NAME = "Voice Memos Exporter"
DEFAULT_APP_VERSION = "1.0.3"
GITHUB_REPO = "teofantsi/voice-memos-exporter"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"

class VoiceMemosExporter:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        
        # Configure root window
        self.root.geometry("1000x600")
        self.root.minsize(800, 400)
        
        # Variables
        self.selected_items = set()
        self.recording_details = {}
        self.db_path = os.path.expanduser("~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db")
        self.recordings_path = os.path.dirname(self.db_path)
        self.search_var = tk.StringVar()
        self.selection_status_var = tk.StringVar(value="0 selected")
        self.updating_selection = False
        self.update_progress_window = None
        self.update_progress_label_var = tk.StringVar(value="")
        
        # Create GUI elements
        self.create_menu()
        self.create_widgets()
        
        # Now bind the search trace
        self.search_var.trace_add('write', self.filter_recordings)
        
        # Load recordings
        self.load_recordings()

    def open_security_preferences(self):
        """Open System Preferences at Security & Privacy > Privacy > Full Disk Access"""
        try:
            subprocess.run(['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'])
        except Exception as e:
            print(f"Error opening System Preferences: {e}")

    def create_menu(self):
        menubar = tk.Menu(self.root)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Check for Updates", command=self.check_for_updates)
        settings_menu.add_separator()
        settings_menu.add_command(label="Open Security Settings", command=self.open_security_preferences)

        menubar.add_cascade(label="Settings", menu=settings_menu)
        self.root.config(menu=menubar)

    def show_permissions_dialog(self):
        """Show a custom dialog with instructions for granting Full Disk Access"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Full Disk Access Required")
        dialog.geometry("500x500")  # Increased height
        dialog.minsize(500, 500)  # Set minimum size
        dialog.transient(self.root)
        dialog.grab_set()

        # Main container frame
        main_frame = ttk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        warning_label = ttk.Label(main_frame, text="⚠️", font=('TkDefaultFont', 48))
        warning_label.pack(pady=10)

        ttk.Label(main_frame, text="Full Disk Access Required", font=('TkDefaultFont', 14, 'bold')).pack(pady=5)
        
        instructions = ttk.Frame(main_frame)
        instructions.pack(fill=tk.BOTH, expand=True, pady=10)
        
        steps = [
            "1. Click 'Open Security Settings' below",
            "2. Click the lock 🔒 icon to make changes",
            "3. Click + to add an application",
            "4. Navigate to and select 'Voice Memos Exporter'",
            "   (the current application you're using)",
            "5. Select the application and click Open",
            "6. Ensure the checkbox next to the application is selected",
            "7. Restart this application"
        ]
        
        for step in steps:
            ttk.Label(instructions, text=step, wraplength=400).pack(anchor='w', pady=2)

        # Button frame at the bottom
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(20, 0))
        
        # Configure button frame columns
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        
        # Add buttons with grid
        ttk.Button(button_frame, text="Open Security Settings", 
                  command=lambda: [self.open_security_preferences(), dialog.destroy()]).grid(row=0, column=0, padx=5, sticky='e')
        ttk.Button(button_frame, text="Close", 
                  command=dialog.destroy).grid(row=0, column=1, padx=5, sticky='w')

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        # Search frame
        search_frame = ttk.Frame(main_frame)
        search_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Create treeview with title column
        self.tree = ttk.Treeview(
            main_frame,
            columns=('title', 'date', 'duration', 'checked', 'path'),
            show='headings',
            displaycolumns=('title', 'date', 'duration', 'checked'),
            selectmode='extended'
        )
        self.tree.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure treeview columns
        self.tree.heading('title', text='Title')
        self.tree.heading('date', text='Date')
        self.tree.heading('duration', text='Duration')
        self.tree.heading('checked', text='Select ☐')
        
        self.tree.column('title', width=300)
        self.tree.column('date', width=200)
        self.tree.column('duration', width=100)
        self.tree.column('checked', width=80, anchor='center')
        self.tree.column('path', width=0, stretch=False)
        
        # Style configuration for better visibility
        style = ttk.Style()
        style.configure("Treeview", rowheight=25)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.grid(row=1, column=2, sticky=(tk.N, tk.S))
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        # Button frame with descriptions
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        
        # Left side buttons with descriptions
        left_frame = ttk.Frame(button_frame)
        left_frame.pack(side=tk.LEFT)
        
        ttk.Button(left_frame, text="Select All", command=self.select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(left_frame, text="Deselect All", command=self.deselect_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(left_frame, text="Delete Selected", command=self.delete_selected).pack(side=tk.LEFT, padx=5)
        ttk.Label(
            left_frame,
            text="Click checkboxes or use Shift-click / Shift-arrow to select multiple items"
        ).pack(side=tk.LEFT, padx=10)
        ttk.Label(button_frame, textvariable=self.selection_status_var).pack(side=tk.RIGHT, padx=(0, 10))
        
        # Right side export button
        ttk.Button(button_frame, text="Export Selected", command=self.export_selected).pack(side=tk.RIGHT, padx=5)
        
        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # Bind click event
        self.tree.bind('<Button-1>', self.on_click)
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)
        self.tree.bind('<space>', self.on_space_key)
        self.tree.bind('<Command-a>', self.on_select_all_shortcut)
        self.tree.bind('<Control-a>', self.on_select_all_shortcut)

    def get_current_app_path(self):
        executable_path = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve()
        for candidate in [executable_path, *executable_path.parents]:
            if candidate.suffix == '.app':
                return str(candidate)
        return None

    def get_current_version(self):
        app_path = self.get_current_app_path()
        if app_path:
            plist_path = os.path.join(app_path, "Contents", "Info.plist")
            if os.path.exists(plist_path):
                try:
                    with open(plist_path, "rb") as plist_file:
                        plist_data = plistlib.load(plist_file)
                    return plist_data.get("CFBundleShortVersionString") or DEFAULT_APP_VERSION
                except Exception:
                    pass
        return DEFAULT_APP_VERSION

    def show_update_progress(self, message):
        if self.update_progress_window and self.update_progress_window.winfo_exists():
            self.update_progress_label_var.set(message)
            return

        self.update_progress_label_var.set(message)
        dialog = tk.Toplevel(self.root)
        dialog.title("Updating")
        dialog.geometry("380x120")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)

        ttk.Label(dialog, textvariable=self.update_progress_label_var, wraplength=320).pack(pady=(20, 10), padx=20)
        progress_bar = ttk.Progressbar(dialog, mode='indeterminate')
        progress_bar.pack(fill=tk.X, padx=20, pady=(0, 20))
        progress_bar.start(10)

        self.update_progress_window = dialog

    def close_update_progress(self):
        if self.update_progress_window and self.update_progress_window.winfo_exists():
            self.update_progress_window.destroy()
        self.update_progress_window = None

    def check_for_updates(self):
        self.show_update_progress("Checking GitHub for the latest release...")
        threading.Thread(target=self._check_for_updates_worker, daemon=True).start()

    def _check_for_updates_worker(self):
        try:
            request = Request(
                LATEST_RELEASE_API,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"{APP_NAME}/{self.get_current_version()}"
                }
            )
            with urlopen(request, timeout=30) as response:
                release_data = json.load(response)
            self.root.after(0, lambda: self._handle_update_check_success(release_data))
        except HTTPError as error:
            self.root.after(0, lambda: self._handle_update_check_error(f"GitHub returned HTTP {error.code}."))
        except URLError as error:
            self.root.after(0, lambda: self._handle_update_check_error(f"Unable to reach GitHub: {error.reason}"))
        except Exception as error:
            self.root.after(0, lambda: self._handle_update_check_error(str(error)))

    def _handle_update_check_error(self, message):
        self.close_update_progress()
        messagebox.showerror("Update Check Failed", f"Could not check for updates.\n\n{message}")

    def _handle_update_check_success(self, release_data):
        self.close_update_progress()

        if release_data.get("draft"):
            messagebox.showinfo("No Published Update", "The latest GitHub release is still a draft.")
            return

        asset = self.find_release_asset(release_data)
        if not asset:
            should_open = messagebox.askyesno(
                "No Downloadable App Found",
                "The latest GitHub release does not include a macOS zip asset yet.\n\nOpen the Releases page?"
            )
            if should_open:
                subprocess.run(['open', RELEASES_PAGE_URL])
            return

        release_label = release_data.get("name") or release_data.get("tag_name") or "latest release"
        current_version = self.get_current_version()
        should_install = messagebox.askyesno(
            "Install Update",
            f"Current app version: {current_version}\n"
            f"Latest GitHub release: {release_label}\n\n"
            "Download and install this release now?"
        )
        if should_install:
            self.show_update_progress(f"Downloading {release_label}...")
            threading.Thread(
                target=self._download_and_install_update_worker,
                args=(asset["browser_download_url"], release_label),
                daemon=True
            ).start()

    def find_release_asset(self, release_data):
        assets = release_data.get("assets", [])
        for asset in assets:
            asset_name = asset.get("name", "")
            if asset_name.endswith(".zip") and "Voice-Memos-Exporter" in asset_name:
                return asset
        return None

    def get_install_target_path(self):
        current_app_path = self.get_current_app_path()
        if current_app_path:
            target_directory = os.path.dirname(current_app_path)
            if os.access(target_directory, os.W_OK):
                return current_app_path

        applications_directory = os.path.expanduser("~/Applications")
        os.makedirs(applications_directory, exist_ok=True)
        return os.path.join(applications_directory, f"{APP_NAME}.app")

    def _download_and_install_update_worker(self, download_url, release_label):
        temp_dir = tempfile.mkdtemp(prefix="voice-memos-updater-")
        zip_path = os.path.join(temp_dir, "update.zip")
        try:
            request = Request(download_url, headers={"User-Agent": f"{APP_NAME}/{self.get_current_version()}"})
            with urlopen(request, timeout=60) as response, open(zip_path, "wb") as zip_file:
                shutil.copyfileobj(response, zip_file)

            self.root.after(0, lambda: self.update_progress_label_var.set(f"Extracting {release_label}..."))
            with zipfile.ZipFile(zip_path, "r") as zip_file:
                zip_file.extractall(temp_dir)

            extracted_app_path = None
            for root_dir, dir_names, _ in os.walk(temp_dir):
                for dir_name in dir_names:
                    if dir_name.endswith(".app"):
                        extracted_app_path = os.path.join(root_dir, dir_name)
                        break
                if extracted_app_path:
                    break

            if not extracted_app_path:
                raise RuntimeError("The downloaded release did not contain a macOS app bundle.")

            target_app_path = self.get_install_target_path()
            installer_script = os.path.join(temp_dir, "install_update.sh")
            installer_contents = f"""#!/bin/bash
set -e
sleep 2
SOURCE_APP={shlex.quote(extracted_app_path)}
TARGET_APP={shlex.quote(target_app_path)}
TEMP_ROOT={shlex.quote(temp_dir)}
BACKUP_APP="${{TARGET_APP}}.backup"

if [ -e "$BACKUP_APP" ]; then
  rm -rf "$BACKUP_APP"
fi

if [ -d "$TARGET_APP" ]; then
  mv "$TARGET_APP" "$BACKUP_APP"
fi

ditto "$SOURCE_APP" "$TARGET_APP"
rm -rf "$BACKUP_APP"
open "$TARGET_APP"
rm -rf "$TEMP_ROOT"
"""
            with open(installer_script, "w", encoding="utf-8") as script_file:
                script_file.write(installer_contents)
            