import os
import struct
import tkinter as tk
import subprocess
import threading
import shutil
import json
import re
import tempfile
import time
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ==========================================
#              CONFIGURATION MANAGER
# ==========================================

class ConfigManager:
    def __init__(self):
        self.settings_dir = os.path.join(os.path.dirname(__file__), "settings")
        self.config_file = os.path.join(self.settings_dir, "config_v23.json")
        
        if not os.path.exists(self.settings_dir):
            os.makedirs(self.settings_dir)
            
        self.default_config = {
            "tool_path": "",
            "decoder_path": "", 
            "extract_input_dir": os.getcwd(),
            "extract_output_dir": os.getcwd(),
            "convert_input_dir": os.getcwd(),
            "convert_output_dir": os.getcwd(),
            "patch_bank_dir": os.getcwd(),
            "patch_wem_dir": os.getcwd(),
            "patch_wav_source_dir": os.getcwd(),
            "patch_output_dir": os.getcwd(),
            "wav_tools_dir": os.getcwd(),
            # UI Persist keys
            "fade_duration": "1.5",
            "trim_fade_duration": "1.5",
            "trim_start": "0",
            "trim_end": "10"
        }
        self.config = self.load_config()

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    
                    # Auto-repair buggy paths from older versions
                    for k in ["tool_path", "decoder_path"]:
                        val = data.get(k, "")
                        if val and val.lower().endswith(".wav"):
                            data[k] = ""

                    for key, val in self.default_config.items():
                        if key not in data:
                            data[key] = val
                    return data
            except:
                return self.default_config.copy()
        return self.default_config.copy()

    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def get(self, key):
        val = self.config.get(key, "")
        return val if val else self.default_config.get(key, "")

    def set(self, key, value):
        self.config[key] = value
        self.save_config()

    def set_path(self, key, path):
        if not path: return
        
        # 1. Handle Tools (Expects a File)
        if key in ["tool_path", "decoder_path"]:
            self.config[key] = path
            
        # 2. Handle Directories (Expects a Folder)
        elif key.endswith("_dir"):
            if os.path.isfile(path):
                self.config[key] = os.path.dirname(path)
            else:
                self.config[key] = path
        else:
            self.config[key] = path
        
        self.save_config()

# ==========================================
#                WAV MANIPULATOR
# ==========================================

class WavManipulator:
    @staticmethod
    def check_ffmpeg(log_func):
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except FileNotFoundError:
            log_func("[ERROR] FFMPEG not found! Please install FFMPEG.\n")
            return False

    @staticmethod
    def get_duration(wav_path):
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", wav_path]
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo)
            return float(result.stdout.strip())
        except:
            return 0.0

    @staticmethod
    def compress_wav(input_path, output_path, sample_rate=44100, channels=2):
        cmd = ["ffmpeg", "-y", "-i", input_path, "-ar", str(sample_rate), "-ac", str(channels), output_path]
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, startupinfo=startupinfo)
            return True
        except:
            return False

    @staticmethod
    def merge_wavs(file_list, output_path, log_func):
        if not file_list: return
        list_file = "ffmpeg_concat_list.txt"
        try:
            with open(list_file, 'w') as f:
                for path in file_list:
                    f.write(f"file '{path}'\n")
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", output_path]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, startupinfo=startupinfo)
            if log_func: log_func(f" [SUCCESS] Created Template: {output_path}\n")
        except Exception as e:
            if log_func: log_func(f" [ERROR] Merge failed: {e}\n")
        finally:
            if os.path.exists(list_file): os.remove(list_file)

    @staticmethod
    def generate_silence(output_path, duration):
        cmd = [
            "ffmpeg", "-y", 
            "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", 
            "-t", str(duration), 
            output_path
        ]
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, startupinfo=startupinfo)
            return True
        except:
            return False

    @staticmethod
    def run_single_trim(input_file, output_file, start_time, end_time, fade_duration, log_func):
        """Standard trimmer included for the UI tab"""
        try:
            duration = end_time - start_time
            if duration <= 0:
                log_func("[ERROR] End time must be greater than start time.\n")
                return

            log_func(f"Trimming: {os.path.basename(input_file)}\n -> Start: {start_time}s, End: {end_time}s (Dur: {duration}s)\n")

            cmd = [
                "ffmpeg", "-y", "-i", input_file,
                "-ss", str(start_time),
                "-t", str(duration)
            ]

            # Fade Logic
            if fade_duration > 0:
                if duration > fade_duration:
                    fade_start = duration - fade_duration
                    filter_str = f"afade=t=out:st={fade_start}:d={fade_duration}"
                    cmd.extend(["-af", filter_str])
                    log_func(f" -> Applying {fade_duration}s fade out.\n")
                else:
                    log_func(" [WARN] Clip too short for fade out. Skipping.\n")

            # Force format for tools
            cmd.extend(["-ac", "1", "-ar", "22050", output_file])

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, startupinfo=startupinfo)
            
            log_func(f" [SUCCESS] Saved to: {output_file}\n")
            
        except Exception as e:
            log_func(f" [ERROR] Trim failed: {e}\n")

    @staticmethod
    def smart_split_and_encode(ordered_file_list, big_file, output_folder, auto_encode, tool_path, fade_duration, log_func):
        if not os.path.exists(output_folder): os.makedirs(output_folder)
        
        if auto_encode:
            found_path, _ = AudioEngine.get_converter_tool(tool_path)
            if found_path:
                tool_path = found_path
                log_func(f"[INFO] Using Conversion Tool: {tool_path}\n")
            else:
                log_func("[ERROR] Cannot auto-encode: Tool not found. Proceeding with split only.\n")
                auto_encode = False

        big_file_duration = WavManipulator.get_duration(big_file)
        current_start = 0.0
        
        log_func(f"Starting Split on: {os.path.basename(big_file)}\n")
        log_func(f"Target: 22050Hz | Mono | Vorbis Quality Low\n")
        
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        for i, ref_file in enumerate(ordered_file_list):
            ref_name = os.path.basename(ref_file)
            duration = WavManipulator.get_duration(ref_file)
            
            if duration <= 0:
                log_func(f" [SKIP] {ref_name} has invalid duration.\n")
                continue

            wav_output_path = os.path.join(output_folder, ref_name)
            is_silence = False

            if current_start >= big_file_duration:
                log_func(f" -> Song ended. Generating SILENCE for {ref_name} ({duration:.2f}s)\n")
                if not WavManipulator.generate_silence(wav_output_path, duration):
                    log_func(f" [ERROR] Failed to generate silence for {ref_name}\n")
                    continue
                is_silence = True
            else:
                cmd = [
                    "ffmpeg", "-y", "-i", big_file,
                    "-ss", str(current_start),
                    "-t", str(duration)
                ]

                # --- Insert Fade Logic Here ---
                if fade_duration > 0 and duration > fade_duration:
                    fade_start = duration - fade_duration
                    filter_str = f"afade=t=out:st={fade_start}:d={fade_duration}"
                    cmd.extend(["-af", filter_str])
                # ------------------------------

                # Force Output Format
                cmd.extend(["-ac", "1", "-ar", "22050", wav_output_path])

                try:
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, startupinfo=startupinfo)
                    log_func(f" -> Cut {ref_name}\n")
                    current_start += duration
                except Exception as e:
                    log_func(f" [ERROR] Failed to cut {ref_name}: {e}\n")
                    continue

            if auto_encode:
                wem_name = os.path.splitext(ref_name)[0] + ".wem"
                wem_output_path = os.path.join(output_folder, wem_name)
                
                if AudioEngine.run_conversion(tool_path, wav_output_path, wem_output_path, "Vorbis Quality Low"):
                      status = " [SILENT WEM]" if is_silence else " [WEM]"
                      log_func(f"    +{status} Encoded: {wem_name}\n")
                else:
                      log_func(f"    ! Encoding Failed: {wem_name}\n")

# ==========================================
#                AUDIO ENGINE
# ==========================================

class AudioEngine:
    @staticmethod
    def get_converter_tool(manual_path=None):
        if manual_path and os.path.exists(manual_path):
            return manual_path, os.path.basename(manual_path)
        script_dir = os.path.dirname(__file__)
        settings_dir = os.path.join(script_dir, "settings")
        possible_tools = ["sound2wem.cmd", "sound2wem.exe", "wwise_pd3.exe"]
        for tool in possible_tools:
            if os.path.exists(os.path.join(settings_dir, tool)): return os.path.join(settings_dir, tool), tool
            if os.path.exists(tool): return os.path.abspath(tool), tool
        return None, None

    @staticmethod
    def run_conversion(tool_path, input_wav, output_wem, quality_flag=""):
        tool_name = os.path.basename(tool_path).lower()
        if tool_path.lower().endswith(('.cmd', '.bat')):
            cmd = ["cmd.exe", "/c", tool_path]
        else:
            cmd = [tool_path]

        if "sound2wem" in tool_name:
            if quality_flag: cmd.append(f'--conversion:{quality_flag}')
            cmd.append(input_wav)
        else:
            cmd.extend(["-encode", input_wav, output_wem])

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        try:
            subprocess.run(cmd, startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        
        wem_name = os.path.basename(output_wem)
        possible_locs = [
            output_wem,
            os.path.join(os.path.dirname(input_wav), wem_name),
            os.path.join(os.getcwd(), wem_name),
            os.path.join(os.path.dirname(tool_path), wem_name)
        ]
        
        found = None
        for loc in possible_locs:
            if loc and os.path.exists(loc):
                found = loc
                break
        
        if found:
            if os.path.abspath(found) != os.path.abspath(output_wem):
                if os.path.exists(output_wem): os.remove(output_wem)
                shutil.move(found, output_wem)
            return True
        return False

    @staticmethod
    def run_decoding(tool_path, input_wem, output_wav):
        """Runs decoder (e.g., vgmstream -o out.wav in.wem)"""
        if not tool_path or not os.path.exists(tool_path): return False
        
        # Standard vgmstream syntax
        cmd = [tool_path, "-o", output_wav, input_wem]
        
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        try:
            subprocess.run(cmd, startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return os.path.exists(output_wav)
        except:
            return False

    @staticmethod
    def parse_bnk(bnk_path, log_func):
        try:
            with open(bnk_path, 'rb') as f: data = bytearray(f.read())
        except Exception as e:
            log_func(f"Error reading file: {e}\n"); return None, None, None, None

        offset, didx_offset, didx_size, data_payload_start = 0, -1, 0, -1
        while offset < len(data) - 8:
            try:
                chunk_id = data[offset : offset+4].decode('ascii', errors='ignore')
                chunk_size = struct.unpack('<I', data[offset+4 : offset+8])[0]
            except: break 
            if chunk_id == "DIDX": didx_offset, didx_size = offset + 8, chunk_size
            elif chunk_id == "DATA": data_payload_start = offset + 8
            offset += 8 + chunk_size

        if didx_offset == -1 or data_payload_start == -1:
            log_func(f"Error: {os.path.basename(bnk_path)} invalid (Missing DIDX/DATA).\n"); return None, None, None, None
        return data, didx_offset, didx_size, data_payload_start

    @staticmethod
    def extract_batch(bnk_paths, base_output_folder, do_decode, decoder_path, log_func):
        if not bnk_paths: return
        if not os.path.exists(base_output_folder): os.makedirs(base_output_folder)
        total = 0
        
        # Validate decoder if needed
        if do_decode and (not decoder_path or not os.path.exists(decoder_path)):
            log_func("[ERROR] Decoder path invalid. Skipping conversion to WAV.\n")
            do_decode = False

        for bnk_path in bnk_paths:
            bnk_name = os.path.basename(bnk_path)
            log_func(f"\nProcessing: {bnk_name}...\n")
            data, didx_offset, didx_size, data_payload_start = AudioEngine.parse_bnk(bnk_path, log_func)
            if data is None: continue

            folder_name = os.path.splitext(bnk_name)[0]
            bank_out_dir = os.path.join(base_output_folder, folder_name)
            if not os.path.exists(bank_out_dir): os.makedirs(bank_out_dir)

            num_files = didx_size // 12
            count = 0
            for i in range(num_files):
                pos = didx_offset + (i * 12)
                fid, foff, fsize = struct.unpack('<III', data[pos:pos+12])
                abs_start = data_payload_start + foff
                
                wem_filename = f"{fid}.wem"
                wem_full_path = os.path.join(bank_out_dir, wem_filename)
                
                with open(wem_full_path, 'wb') as out_f:
                    out_f.write(data[abs_start : abs_start + fsize])
                
                # --- AUTO DECODE ---
                if do_decode:
                    wav_filename = f"{fid}.wav"
                    wav_full_path = os.path.join(bank_out_dir, wav_filename)
                    if AudioEngine.run_decoding(decoder_path, wem_full_path, wav_full_path):
                        pass # log_func(f"   + Decoded {wav_filename}\n")
                    else:
                        log_func(f"   ! Failed to decode {wem_filename}\n")

                count += 1
            log_func(f" -> Extracted {count} files\n"); total += count
        messagebox.showinfo("Done", f"Extracted {total} files.")

    @staticmethod
    def convert_batch(wav_paths, output_dir, quality_flag, manual_tool_path, log_func):
        tool_path, _ = AudioEngine.get_converter_tool(manual_tool_path)
        if not tool_path: log_func("[ERROR] Conversion tool not found.\n"); return
        if not os.path.exists(output_dir): os.makedirs(output_dir)
        success = 0
        for wav_path in wav_paths:
            wem_name = os.path.splitext(os.path.basename(wav_path))[0] + ".wem"
            target = os.path.join(output_dir, wem_name)
            log_func(f"Converting: {os.path.basename(wav_path)}...\n")
            if AudioEngine.run_conversion(tool_path, wav_path, target, quality_flag):
                log_func(f" [OK] Saved {wem_name}\n"); success += 1
            else: log_func(f" [FAIL] Conversion failed\n")
        messagebox.showinfo("Done", f"Converted {success} files.")

    @staticmethod
    def patch_batch(bnk_paths, wem_dir, wav_source_dir, output_dir, tool_path, enable_auto_shrink, log_func):
        if not bnk_paths: return
        if not os.path.exists(output_dir): os.makedirs(output_dir)
        
        available_wems = {}
        if os.path.exists(wem_dir):
            for f in os.listdir(wem_dir):
                if f.lower().endswith('.wem'): available_wems[os.path.splitext(f)[0]] = os.path.join(wem_dir, f)
        
        can_shrink = False
        if enable_auto_shrink and WavManipulator.check_ffmpeg(log_func):
            tool_path, _ = AudioEngine.get_converter_tool(tool_path)
            if tool_path: can_shrink = True
            else: log_func("[WARN] Converter tool missing. Auto-shrink disabled.\n")

        temp_dir = tempfile.mkdtemp()
        total_patched = 0
        try:
            for bnk_path in bnk_paths:
                bnk_filename = os.path.basename(bnk_path)
                log_func(f"\nScanning Bank: {bnk_filename}...\n")
                data, didx_offset, didx_size, data_payload_start = AudioEngine.parse_bnk(bnk_path, log_func)
                if data is None: continue

                bnk_index = {}
                num_files = didx_size // 12
                for i in range(num_files):
                    pos = didx_offset + (i * 12)
                    fid, foff, fsize = struct.unpack('<III', data[pos:pos+12])
                    bnk_index[str(fid)] = {'didx_pos': pos, 'file_offset': foff, 'max_size': fsize}

                files_patched = 0
                for wem_id, wem_path in available_wems.items():
                    if wem_id in bnk_index:
                        slot = bnk_index[wem_id]
                        max_size = slot['max_size']
                        final_inject_path = wem_path
                        current_size = os.path.getsize(wem_path)

                        if current_size > max_size:
                            log_func(f" [WARN] {wem_id}: Too big ({current_size} > {max_size}).\n")
                            if can_shrink:
                                log_func(f"    -> Attempting Auto-Compression...\n")
                                source_wav = os.path.join(wav_source_dir, f"{wem_id}.wav")
                                if not os.path.exists(source_wav): source_wav = os.path.join(wem_dir, f"{wem_id}.wav")
                                
                                if os.path.exists(source_wav):
                                    attempts = [(44100, 1), (32000, 2), (32000, 1), (24000, 1), (22050, 1)]
                                    success_shrink = False
                                    for sr, ch in attempts:
                                        t_wav, t_wem = os.path.join(temp_dir, f"t_{wem_id}.wav"), os.path.join(temp_dir, f"t_{wem_id}.wem")
                                        if WavManipulator.compress_wav(source_wav, t_wav, sr, ch):
                                            if AudioEngine.run_conversion(tool_path, t_wav, t_wem):
                                                t_size = os.path.getsize(t_wem)
                                                if t_size <= max_size:
                                                    log_func(f"    -> Fits! ({t_size} bytes)\n"); final_inject_path = t_wem; current_size = t_size; success_shrink = True; break
                                    if not success_shrink:
                                        log_func("    -> Failed to shrink enough. Skipping.\n"); continue
                                else:
                                    log_func("    -> Source WAV not found. Skipping.\n"); continue
                            else: continue

                        abs_start = data_payload_start + slot['file_offset']
                        with open(final_inject_path, 'rb') as f: new_content = f.read()
                        
                        if len(new_content) > max_size: log_func(f" [ERROR] Still too big. Aborting inject.\n"); continue
                        data[abs_start : abs_start + current_size] = new_content
                        padding = max_size - current_size
                        if padding > 0: data[abs_start + current_size : abs_start + max_size] = b'\x00' * padding
                        struct.pack_into('<I', data, slot['didx_pos'] + 8, current_size)
                        log_func(f" [INJECTED] ID {wem_id}\n"); files_patched += 1

                if files_patched > 0:
                    out_name = os.path.join(output_dir, bnk_filename)
                    with open(out_name, 'wb') as f: f.write(data)
                    log_func(f" [SUCCESS] Saved: {out_name}\n"); total_patched += 1
                else: log_func(" [INFO] No replacements found.\n")
        except Exception as e: log_func(f"[CRITICAL ERROR] {e}\n")
        finally: shutil.rmtree(temp_dir)
        messagebox.showinfo("Patch Complete", f"Modified: {total_patched} banks")

# ==========================================
#              GUI IMPLEMENTATION
# ==========================================

class EchoToolApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Echo VR Audio Tool v23 (Merged)")
        self.root.geometry("900x980")
        self.cfg = ConfigManager()
        
        self.bg_color = "#121212"
        self.fg_color = "#E0E0E0"
        self.entry_bg = "#2C2C2C"
        self.btn_bg = "#333333"
        self.accent_color = "#007ACC"
        self.success_color = "#2E7D32"
        self.warn_color = "#D84315"
        self.root.configure(bg=self.bg_color)
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TNotebook", background=self.bg_color, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.btn_bg, foreground=self.fg_color, padding=[10, 8])
        style.map("TNotebook.Tab", background=[("selected", self.accent_color)], foreground=[("selected", "white")])
        style.configure("TFrame", background=self.bg_color)
        
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, expand=True, fill='both')
        self.tab_extract = ttk.Frame(self.notebook)
        self.tab_wav = ttk.Frame(self.notebook)
        self.tab_convert = ttk.Frame(self.notebook)
        self.tab_patch = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_extract, text="  EXTRACT  ")
        self.notebook.add(self.tab_wav, text="  SEQUENCER / TRIMMER  ")
        self.notebook.add(self.tab_convert, text="  CONVERT  ")
        self.notebook.add(self.tab_patch, text="  PATCH (REBUILD)  ")

        self.selected_bnks_extract = []
        self.selected_wavs_convert = []
        self.selected_bnks_patch = []
        self.seq_files = [] 

        self.setup_extract_tab()
        self.setup_wav_tab()
        self.setup_convert_tab()
        self.setup_patch_tab()

        lbl = tk.Label(root, text="System Log:", bg=self.bg_color, fg="gray")
        lbl.pack(anchor="w", padx=10)
        self.log_text = scrolledtext.ScrolledText(root, height=10, bg="#080808", fg="#00FF00", insertbackground="white")
        self.log_text.pack(fill='both', expand=True, padx=10, pady=(0, 10))

    def log(self, msg):
        self.log_text.insert(tk.END, msg); self.log_text.see(tk.END)

    def create_label(self, parent, text, color=None):
        return tk.Label(parent, text=text, bg=self.bg_color, fg=color if color else self.fg_color, font=("Segoe UI", 10, "bold"))

    def create_entry_row(self, parent, btn_cmd, default_text=""):
        frame = tk.Frame(parent, bg=self.bg_color)
        frame.pack(fill=tk.X, padx=20)
        entry = tk.Entry(frame, bg=self.entry_bg, fg="white", insertbackground="white", relief="flat")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        if default_text: entry.insert(0, default_text)
        tk.Button(frame, text="...", bg=self.btn_bg, fg="white", relief="flat", width=4, command=btn_cmd).pack(side=tk.RIGHT, padx=5)
        return entry

    def save_ui_state(self):
        """Forces all UI values into config before running operations"""
        self.cfg.set('decoder_path', self.e_decoder.get())
        self.cfg.set('extract_output_dir', self.e_out_ex.get())
        
        # Splitter Settings
        self.cfg.set('fade_duration', self.e_fade_dur.get())
        
        # Trimmer Settings
        self.cfg.set('trim_start', self.e_trim_start.get())
        self.cfg.set('trim_end', self.e_trim_end.get())
        self.cfg.set('trim_fade_duration', self.e_trim_fade.get())
        
        self.cfg.set('tool_path', self.e_tool_cv.get())
        self.cfg.set('convert_output_dir', self.e_out_cv.get())
        self.cfg.set('patch_wem_dir', self.e_wem_pt.get())
        self.cfg.set('patch_wav_source_dir', self.e_wav_src_pt.get())
        self.cfg.set('patch_output_dir', self.e_out_pt.get())

    # --- 1. EXTRACT ---
    def setup_extract_tab(self):
        f = self.tab_extract
        self.create_label(f, "Select Bank Files:").pack(pady=(20, 5))
        self.e_bnk_ex = self.create_entry_row(f, self.browse_bnks_ex)
        self.create_label(f, "Output Folder:").pack(pady=(20, 5))
        self.e_out_ex = self.create_entry_row(f, lambda: self.browse_folder('extract_output_dir', self.e_out_ex))
        self.e_out_ex.insert(0, self.cfg.get('extract_output_dir'))
        
        lf_dec = tk.LabelFrame(f, text=" Optional Conversion ", bg=self.bg_color, fg=self.fg_color)
        lf_dec.pack(fill=tk.X, padx=20, pady=10)
        self.var_extract_wav = tk.BooleanVar(value=False)
        tk.Checkbutton(lf_dec, text="Convert to WAV", variable=self.var_extract_wav, bg=self.bg_color, fg="white", selectcolor=self.bg_color).pack(anchor="w", padx=10, pady=5)
        tk.Label(lf_dec, text="Decoder Tool (vgmstream):", bg=self.bg_color, fg="gray").pack(anchor="w", padx=10)
        self.e_decoder = self.create_entry_row(lf_dec, self.browse_decoder); self.e_decoder.insert(0, self.cfg.get('decoder_path'))
        tk.Button(f, text="START EXTRACTION", bg=self.accent_color, fg="white", font=("Segoe UI", 10, "bold"), relief="flat", pady=8, command=self.run_extract).pack(pady=20, fill=tk.X, padx=150)

    # --- 2. SEQUENCER & TRIMMER ---
    def setup_wav_tab(self):
        f = self.tab_wav
        # Left Panel (Sequence List)
        frame_list = tk.Frame(f, bg=self.bg_color)
        frame_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.create_label(frame_list, "Step 1: Original Sequence").pack(anchor="w")
        self.lb_seq = tk.Listbox(frame_list, bg="#1E1E1E", fg="white", selectbackground=self.accent_color, height=15)
        self.lb_seq.pack(fill=tk.BOTH, expand=True, pady=5)
        btn_box = tk.Frame(frame_list, bg=self.bg_color)
        btn_box.pack(fill=tk.X)
        tk.Button(btn_box, text="+ Add", command=self.seq_add).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_box, text="- Remove", command=self.seq_rem).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_box, text="▼ Down", command=self.seq_down).pack(side=tk.RIGHT, padx=2)
        tk.Button(btn_box, text="▲ Up", command=self.seq_up).pack(side=tk.RIGHT, padx=2)

        # Right Panel (Operations)
        frame_act = tk.Frame(f, bg=self.bg_color)
        frame_act.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # --- MERGE ---
        tk.Label(frame_act, text="Visualize Original:", bg=self.bg_color, fg=self.fg_color, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0,5))
        tk.Button(frame_act, text="CREATE REFERENCE TEMPLATE", bg="#555", fg="white", command=self.run_seq_merge).pack(fill=tk.X, pady=5)
        tk.Label(frame_act, text="--------------------------------", bg=self.bg_color, fg="#333").pack(pady=5)
        
        # --- SPLIT ---
        self.create_label(frame_act, "Step 2: Split Custom File").pack(anchor="w")
        self.e_big_file = self.create_entry_row(frame_act, self.browse_big_file)
        
        # FADE OPTIONS (SPLITTER)
        fade_frame = tk.Frame(frame_act, bg=self.bg_color)
        fade_frame.pack(fill=tk.X, pady=5)
        self.var_fade = tk.BooleanVar(value=True)
        tk.Checkbutton(fade_frame, text="Apply Fade Out", variable=self.var_fade, bg=self.bg_color, fg="white", selectcolor=self.bg_color).pack(side=tk.LEFT)
        tk.Label(fade_frame, text="Duration (s):", bg=self.bg_color, fg="gray").pack(side=tk.LEFT, padx=(10, 5))
        self.e_fade_dur = tk.Entry(fade_frame, width=5, bg=self.entry_bg, fg="white", insertbackground="white")
        self.e_fade_dur.pack(side=tk.LEFT)
        self.e_fade_dur.insert(0, self.cfg.get('fade_duration'))

        self.var_auto_enc_split = tk.BooleanVar(value=True)
        tk.Checkbutton(frame_act, text="Auto-Encode Split Files", variable=self.var_auto_enc_split, bg=self.bg_color, fg="white", selectcolor=self.bg_color).pack(anchor="w", pady=5)
        tk.Button(frame_act, text="SPLIT & MATCH SEQUENCE", bg=self.warn_color, fg="white", font=("Segoe UI", 11, "bold"), height=2, command=self.run_seq_split).pack(fill=tk.X, pady=10)

        # --- TRIM ---
        lf_trim = tk.LabelFrame(frame_act, text=" Step 3: Single File Trimmer ", bg=self.bg_color, fg="white", padx=10, pady=10)
        lf_trim.pack(fill=tk.X, pady=10)
        
        self.e_trim_file = self.create_entry_row(lf_trim, self.browse_trim_file)
        
        # Time Row
        time_frame = tk.Frame(lf_trim, bg=self.bg_color)
        time_frame.pack(fill=tk.X, pady=5)
        tk.Label(time_frame, text="Start (s):", bg=self.bg_color, fg="white").pack(side=tk.LEFT)
        self.e_trim_start = tk.Entry(time_frame, width=8, bg=self.entry_bg, fg="white", insertbackground="white")
        self.e_trim_start.pack(side=tk.LEFT, padx=5)
        self.e_trim_start.insert(0, self.cfg.get('trim_start'))
        
        tk.Label(time_frame, text="End (s):", bg=self.bg_color, fg="white").pack(side=tk.LEFT, padx=(10, 0))
        self.e_trim_end = tk.Entry(time_frame, width=8, bg=self.entry_bg, fg="white", insertbackground="white")
        self.e_trim_end.pack(side=tk.LEFT, padx=5)
        self.e_trim_end.insert(0, self.cfg.get('trim_end'))
        
        # Trim Fade Row
        trim_fade_frame = tk.Frame(lf_trim, bg=self.bg_color)
        trim_fade_frame.pack(fill=tk.X, pady=5)
        self.var_trim_fade = tk.BooleanVar(value=True)
        tk.Checkbutton(trim_fade_frame, text="Apply Fade Out", variable=self.var_trim_fade, bg=self.bg_color, fg="white", selectcolor=self.bg_color).pack(side=tk.LEFT)
        tk.Label(trim_fade_frame, text="Duration (s):", bg=self.bg_color, fg="gray").pack(side=tk.LEFT, padx=(10, 5))
        self.e_trim_fade = tk.Entry(trim_fade_frame, width=6, bg=self.entry_bg, fg="white", insertbackground="white")
        self.e_trim_fade.pack(side=tk.LEFT)
        self.e_trim_fade.insert(0, self.cfg.get('trim_fade_duration'))

        tk.Button(lf_trim, text="CUT FILE", bg="#00897B", fg="white", font=("Segoe UI", 9, "bold"), command=self.run_trim_single).pack(fill=tk.X, pady=5)


    # --- 3. CONVERT ---
    def setup_convert_tab(self):
        f = self.tab_convert
        self.create_label(f, "Tool Path (sound2wem/wwise_cli):").pack(pady=(15, 5))
        self.e_tool_cv = self.create_entry_row(f, self.browse_tool_path); self.e_tool_cv.insert(0, self.cfg.get('tool_path'))
        self.create_label(f, "Select WAV Files:").pack(pady=(15, 5))
        self.e_wav_cv = self.create_entry_row(f, self.browse_wavs_cv)
        self.create_label(f, "Output Folder:").pack(pady=(15, 5))
        self.e_out_cv = self.create_entry_row(f, lambda: self.browse_folder('convert_output_dir', self.e_out_cv)); self.e_out_cv.insert(0, self.cfg.get('convert_output_dir'))
        tk.Button(f, text="CONVERT", bg=self.accent_color, fg="white", font=("Segoe UI", 10, "bold"), relief="flat", pady=10, command=self.run_convert).pack(pady=20, fill=tk.X, padx=150)

    # --- 4. PATCH ---
    def setup_patch_tab(self):
        f = self.tab_patch
        self.create_label(f, "Original Bank Files:").pack(pady=(10, 2))
        self.e_bnk_pt = self.create_entry_row(f, self.browse_bnks_pt)
        self.create_label(f, "Folder with REPLACEMENT .wems:").pack(pady=(10, 2))
        tk.Label(f, text="(Files must be named ID.wem)", bg=self.bg_color, fg="gray").pack()
        self.e_wem_pt = self.create_entry_row(f, lambda: self.browse_folder('patch_wem_dir', self.e_wem_pt)); self.e_wem_pt.insert(0, self.cfg.get('patch_wem_dir'))
        
        # Auto-shrink GUI
        frame_adv = tk.LabelFrame(f, text=" Smart Auto-Fit ", bg=self.bg_color, fg="#4FC3F7")
        frame_adv.pack(fill=tk.X, padx=20, pady=10)
        self.var_autoshrink = tk.BooleanVar(value=True)
        tk.Checkbutton(frame_adv, text="If WEM is too big, auto-compress original WAV", variable=self.var_autoshrink, bg=self.bg_color, fg="white", selectcolor=self.bg_color).pack(anchor="w", padx=5, pady=5)
        self.e_wav_src_pt = self.create_entry_row(frame_adv, lambda: self.browse_folder('patch_wav_source_dir', self.e_wav_src_pt)); self.e_wav_src_pt.insert(0, self.cfg.get('patch_wav_source_dir'))

        self.create_label(f, "Output Folder:").pack(pady=(10, 2))
        self.e_out_pt = self.create_entry_row(f, lambda: self.browse_folder('patch_output_dir', self.e_out_pt)); self.e_out_pt.insert(0, self.cfg.get('patch_output_dir'))
        tk.Button(f, text="REBUILD BANK", bg=self.success_color, fg="white", font=("Segoe UI", 11, "bold"), relief="flat", pady=10, command=self.run_patch).pack(pady=20, fill=tk.X, padx=100)

    # --- LISTBOX & BROWSERS ---
    def seq_add(self):
        fs = filedialog.askopenfilenames(initialdir=self.cfg.get('wav_tools_dir'), filetypes=[("WAV", "*.wav")])
        if fs:
            for f in fs: self.seq_files.append(f); self.lb_seq.insert(tk.END, os.path.basename(f))
            self.cfg.set_path('wav_tools_dir', fs[0])
    def seq_rem(self):
        sel = self.lb_seq.curselection()
        if sel: idx = sel[0]; self.lb_seq.delete(idx); del self.seq_files[idx]
    def seq_up(self):
        sel = self.lb_seq.curselection()
        if not sel or sel[0] == 0: return
        idx = sel[0]; text = self.lb_seq.get(idx); file = self.seq_files[idx]
        self.lb_seq.delete(idx); self.lb_seq.insert(idx-1, text); del self.seq_files[idx]; self.seq_files.insert(idx-1, file); self.lb_seq.selection_set(idx-1)
    def seq_down(self):
        sel = self.lb_seq.curselection()
        if not sel or sel[0] == len(self.seq_files)-1: return
        idx = sel[0]; text = self.lb_seq.get(idx); file = self.seq_files[idx]
        self.lb_seq.delete(idx); self.lb_seq.insert(idx+1, text); del self.seq_files[idx]; self.seq_files.insert(idx+1, file); self.lb_seq.selection_set(idx+1)

    def browse_tool_path(self):
        f = filedialog.askopenfilename(initialdir=os.path.dirname(self.cfg.get('tool_path')), filetypes=[("Tools", "*.cmd *.exe")])
        if f: self.e_tool_cv.delete(0, tk.END); self.e_tool_cv.insert(0, f); self.cfg.set_path('tool_path', f)
    def browse_decoder(self):
        f = filedialog.askopenfilename(initialdir=os.path.dirname(self.cfg.get('decoder_path')), filetypes=[("Tools", "*.exe")])
        if f: self.e_decoder.delete(0, tk.END); self.e_decoder.insert(0, f); self.cfg.set_path('decoder_path', f)
    def browse_folder(self, key, widget):
        d = filedialog.askdirectory(initialdir=self.cfg.get(key))
        if d: widget.delete(0, tk.END); widget.insert(0, d); self.cfg.set_path(key, d)
    def browse_bnks_ex(self):
        fs = filedialog.askopenfilenames(initialdir=self.cfg.get('extract_input_dir'), filetypes=[("All Files", "*.*"), ("Banks", "*.bnk")])
        if fs: self.selected_bnks_extract = fs; self.e_bnk_ex.delete(0, tk.END); self.e_bnk_ex.insert(0, f"{len(fs)} selected"); self.cfg.set_path('extract_input_dir', fs[0])
    def browse_wavs_cv(self):
        fs = filedialog.askopenfilenames(initialdir=self.cfg.get('convert_input_dir'), filetypes=[("WAV", "*.wav")])
        if fs: self.selected_wavs_convert = fs; self.e_wav_cv.delete(0, tk.END); self.e_wav_cv.insert(0, f"{len(fs)} selected"); self.cfg.set_path('convert_input_dir', fs[0])
    def browse_bnks_pt(self):
        fs = filedialog.askopenfilenames(initialdir=self.cfg.get('patch_bank_dir'), filetypes=[("All Files", "*.*"), ("Banks", "*.bnk")])
        if fs: self.selected_bnks_patch = fs; self.e_bnk_pt.delete(0, tk.END); self.e_bnk_pt.insert(0, f"{len(fs)} selected"); self.cfg.set_path('patch_bank_dir', fs[0])
    def browse_big_file(self):
        f = filedialog.askopenfilename(initialdir=self.cfg.get('wav_tools_dir'), filetypes=[("WAV", "*.wav")])
        if f: self.e_big_file.delete(0, tk.END); self.e_big_file.insert(0, f)
    def browse_trim_file(self):
        f = filedialog.askopenfilename(initialdir=self.cfg.get('wav_tools_dir'), filetypes=[("WAV", "*.wav")])
        if f: self.e_trim_file.delete(0, tk.END); self.e_trim_file.insert(0, f)

    # --- ACTIONS ---
    def run_extract(self):
        self.save_ui_state()
        threading.Thread(target=AudioEngine.extract_batch, args=(self.selected_bnks_extract, self.e_out_ex.get(), self.var_extract_wav.get(), self.e_decoder.get(), self.log)).start()
    
    def run_convert(self): 
        self.save_ui_state()
        threading.Thread(target=AudioEngine.convert_batch, args=(self.selected_wavs_convert, self.e_out_cv.get(), "Vorbis Quality High", self.e_tool_cv.get(), self.log)).start()
    
    def run_patch(self): 
        self.save_ui_state()
        threading.Thread(target=AudioEngine.patch_batch, args=(self.selected_bnks_patch, self.e_wem_pt.get(), self.e_wav_src_pt.get(), self.e_out_pt.get(), self.e_tool_cv.get(), self.var_autoshrink.get(), self.log)).start()
    
    def run_seq_merge(self):
        if len(self.seq_files) < 2: messagebox.showwarning("Info", "Add at least 2 files."); return
        out_f = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV", "*.wav")], initialfile="Reference_Template.wav")
        if out_f: threading.Thread(target=WavManipulator.merge_wavs, args=(self.seq_files, out_f, self.log)).start()
    
    def run_seq_split(self):
        self.save_ui_state()
        big_f = self.e_big_file.get()
        if not self.seq_files or not big_f: messagebox.showwarning("Missing Info", "Missing files."); return
        
        tool_path = self.e_tool_cv.get(); do_encode = self.var_auto_enc_split.get()
        if not tool_path: tool_path = self.cfg.get('tool_path')
        
        fade_sec = 0.0
        if self.var_fade.get():
            try: fade_sec = float(self.e_fade_dur.get())
            except: self.log("[WARN] Invalid fade duration, using 0s.\n")
        
        out_dir = os.path.join(os.path.dirname(big_f), "Split_Output")
        threading.Thread(target=WavManipulator.smart_split_and_encode, args=(self.seq_files, big_f, out_dir, do_encode, tool_path, fade_sec, self.log)).start()

    def run_trim_single(self):
        self.save_ui_state()
        f_path = self.e_trim_file.get()
        if not os.path.exists(f_path): messagebox.showwarning("Error", "File not found."); return

        try:
            start = float(self.e_trim_start.get())
            end = float(self.e_trim_end.get())
            fade = float(self.e_trim_fade.get()) if self.var_trim_fade.get() else 0.0
        except ValueError:
            messagebox.showwarning("Error", "Please enter valid numbers for Time and Fade."); return

        out_f = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV", "*.wav")], initialfile=f"Cut_{os.path.basename(f_path)}")
        if out_f:
            threading.Thread(target=WavManipulator.run_single_trim, args=(f_path, out_f, start, end, fade, self.log)).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = EchoToolApp(root)
    root.mainloop()
