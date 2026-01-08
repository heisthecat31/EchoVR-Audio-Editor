import os
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ==========================================
#               CORE LOGIC
# ==========================================

class AudioEngine:
    @staticmethod
    def parse_bnk(bnk_path, log_func):
        """Helper to read BNK and return data + chunk info."""
        try:
            with open(bnk_path, 'rb') as f:
                data = bytearray(f.read())
        except Exception as e:
            log_func(f"Error reading file: {e}\n")
            return None, None, None, None

        offset = 0
        didx_offset = -1
        didx_size = 0
        data_payload_start = -1

        # Scan chunks
        while offset < len(data) - 8:
            try:
                chunk_id = data[offset : offset+4].decode('ascii', errors='ignore')
                chunk_size = struct.unpack('<I', data[offset+4 : offset+8])[0]
            except:
                break 

            if chunk_id == "DIDX":
                didx_offset = offset + 8
                didx_size = chunk_size
            elif chunk_id == "DATA":
                data_payload_start = offset + 8
            
            offset += 8 + chunk_size

        if didx_offset == -1 or data_payload_start == -1:
            log_func(f"Error: {os.path.basename(bnk_path)} is invalid (Missing DIDX or DATA).\n")
            return None, None, None, None

        return data, didx_offset, didx_size, data_payload_start

    @staticmethod
    def extract_batch(bnk_paths, base_output_folder, log_func):
        if not bnk_paths:
            log_func("Error: No bank files selected.\n")
            return

        if not os.path.exists(base_output_folder):
            os.makedirs(base_output_folder)

        total_extracted = 0
        
        for bnk_path in bnk_paths:
            bnk_name = os.path.basename(bnk_path)
            log_func(f"\nProcessing: {bnk_name}...\n")
            
            data, didx_offset, didx_size, data_payload_start = AudioEngine.parse_bnk(bnk_path, log_func)
            if data is None: continue

            # Create Subfolder for this specific bank
            # e.g. Output/Init_bnk/
            subfolder_name = os.path.splitext(bnk_name)[0]
            bank_out_dir = os.path.join(base_output_folder, subfolder_name)
            if not os.path.exists(bank_out_dir):
                os.makedirs(bank_out_dir)

            num_files = didx_size // 12
            count = 0
            
            for i in range(num_files):
                pos = didx_offset + (i * 12)
                fid, foff, fsize = struct.unpack('<III', data[pos:pos+12])
                
                abs_start = data_payload_start + foff
                file_content = data[abs_start : abs_start + fsize]
                
                out_name = os.path.join(bank_out_dir, f"{fid}.wem")
                with open(out_name, 'wb') as out_f:
                    out_f.write(file_content)
                
                count += 1
            
            log_func(f" -> Extracted {count} files to '{subfolder_name}/'\n")
            total_extracted += count

        log_func(f"\nBATCH COMPLETE! Total extracted: {total_extracted}\n")
        messagebox.showinfo("Done", f"Batch extraction finished.\nTotal files: {total_extracted}")

    @staticmethod
    def patch(bnk_path, wem_folder, log_func):
        if not os.path.exists(bnk_path):
            log_func("Error: Bank file not found.\n")
            return

        log_func(f"Analyzing Bank: {os.path.basename(bnk_path)}...\n")
        data, didx_offset, didx_size, data_payload_start = AudioEngine.parse_bnk(bnk_path, log_func)
        if data is None: return

        # Index the bank
        bnk_index = {}
        num_files = didx_size // 12
        for i in range(num_files):
            pos = didx_offset + (i * 12)
            fid, foff, fsize = struct.unpack('<III', data[pos:pos+12])
            bnk_index[fid] = {'didx_pos': pos, 'file_offset': foff, 'max_size': fsize}

        # Find Replacements
        log_func(f"Scanning '{wem_folder}' for replacements...\n")
        success_count = 0
        fail_count = 0
        
        files = [f for f in os.listdir(wem_folder) if f.lower().endswith('.wem')]
        if not files:
            log_func("No .wem files found in folder.\n")
            return

        for filename in files:
            try:
                fid = int(filename.split('.')[0])
            except:
                continue # Skip non-ID filenames

            if fid not in bnk_index:
                # Silent skip for files belonging to other banks
                continue

            slot = bnk_index[fid]
            full_path = os.path.join(wem_folder, filename)
            new_size = os.path.getsize(full_path)
            max_size = slot['max_size']

            if new_size > max_size:
                diff = new_size - max_size
                log_func(f" [FAIL] {fid}: Too big by {diff} bytes.\n")
                fail_count += 1
                continue

            # Inject
            abs_start = data_payload_start + slot['file_offset']
            with open(full_path, 'rb') as f:
                new_content = f.read()
            
            # Overwrite & Pad
            data[abs_start : abs_start + new_size] = new_content
            padding = max_size - new_size
            if padding > 0:
                data[abs_start + new_size : abs_start + max_size] = b'\x00' * padding
            
            # Update DIDX size
            struct.pack_into('<I', data, slot['didx_pos'] + 8, new_size)
            log_func(f" [OK] Patched ID {fid}\n")
            success_count += 1

        if success_count > 0:
            out_name = bnk_path + "_MODDED"
            with open(out_name, 'wb') as f:
                f.write(data)
            log_func(f"\nSUCCESS! Saved as: {os.path.basename(out_name)}\n")
            messagebox.showinfo("Patch Complete", f"Patched {success_count} files.\nRenamed output to original name to use.")
        else:
            log_func("\nNo matching IDs found in this bank.\n")

# ==========================================
#               DARK MODE GUI
# ==========================================

class EchoToolApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Echo VR Audio Tool (Black Edition)")
        self.root.geometry("700x600")
        
        # --- THEME COLORS ---
        self.bg_color = "#121212"
        self.fg_color = "#E0E0E0"
        self.entry_bg = "#2C2C2C"
        self.btn_bg = "#333333"
        self.accent_color = "#007ACC" # Blue for actions
        self.success_color = "#2E7D32" # Green

        self.root.configure(bg=self.bg_color)
        
        # Style Configuration
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure Notebook (Tabs) Colors
        style.configure("TNotebook", background=self.bg_color, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.btn_bg, foreground=self.fg_color, padding=[10, 5])
        style.map("TNotebook.Tab", background=[("selected", self.accent_color)], foreground=[("selected", "white")])
        
        style.configure("TFrame", background=self.bg_color)
        
        # --- TABS ---
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, expand=True, fill='both')

        self.tab_extract = ttk.Frame(self.notebook)
        self.tab_patch = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_extract, text="  EXTRACT (Batch)  ")
        self.notebook.add(self.tab_patch, text="  PATCH (Replace)  ")

        self.selected_bnks_extract = [] # List to store multiple files

        self.setup_extract_tab()
        self.setup_patch_tab()

        # Shared Log
        lbl = tk.Label(root, text="System Log:", bg=self.bg_color, fg=self.fg_color)
        lbl.pack(anchor="w", padx=10)
        
        self.log_text = scrolledtext.ScrolledText(root, height=12, bg="#000000", fg="#00FF00", insertbackground="white")
        self.log_text.pack(fill='both', expand=True, padx=10, pady=(0, 10))

    def log(self, msg):
        self.log_text.insert(tk.END, msg)
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    # --- HELPERS FOR UI ---
    def create_label(self, parent, text):
        return tk.Label(parent, text=text, bg=self.bg_color, fg=self.fg_color, font=("Arial", 10, "bold"))

    def create_entry_row(self, parent, btn_cmd):
        frame = tk.Frame(parent, bg=self.bg_color)
        frame.pack(fill=tk.X, padx=20)
        
        entry = tk.Entry(frame, bg=self.entry_bg, fg="white", insertbackground="white", relief="flat")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        
        btn = tk.Button(frame, text="Browse", bg=self.btn_bg, fg="white", relief="flat", command=btn_cmd)
        btn.pack(side=tk.RIGHT, padx=5)
        return entry

    # --- EXTRACT TAB ---
    def setup_extract_tab(self):
        f = self.tab_extract
        
        self.create_label(f, "1. Select Bank Files (.bnk):").pack(pady=(20, 5))
        self.e_bnk_ex = self.create_entry_row(f, self.browse_bnks_ex)
        
        self.create_label(f, "2. Select Output Folder:").pack(pady=(20, 5))
        self.e_out_ex = self.create_entry_row(f, lambda: self.browse_folder(self.e_out_ex))

        tk.Button(f, text="START BATCH EXTRACTION", bg=self.accent_color, fg="white", font=("Arial", 11, "bold"),
                  relief="flat", pady=10, command=self.run_extract).pack(pady=40, fill=tk.X, padx=100)
        
        tk.Label(f, text="* Creates a subfolder for each bank automatically", bg=self.bg_color, fg="#888888").pack()

    # --- PATCH TAB ---
    def setup_patch_tab(self):
        f = self.tab_patch
        
        self.create_label(f, "1. Select Target Bank File (Single):").pack(pady=(20, 5))
        self.e_bnk_pt = self.create_entry_row(f, lambda: self.browse_file(self.e_bnk_pt))
        
        self.create_label(f, "2. Select Folder with Modded .wems:").pack(pady=(20, 5))
        self.e_wem_pt = self.create_entry_row(f, lambda: self.browse_folder(self.e_wem_pt))

        tk.Button(f, text="INJECT FILES (SURGICAL)", bg=self.success_color, fg="white", font=("Arial", 11, "bold"),
                  relief="flat", pady=10, command=self.run_patch).pack(pady=40, fill=tk.X, padx=100)

    # --- ACTIONS ---
    def browse_bnks_ex(self):
        files = filedialog.askopenfilenames(title="Select Bank Files")
        if files:
            self.selected_bnks_extract = list(files)
            # Display count in entry
            self.e_bnk_ex.delete(0, tk.END)
            self.e_bnk_ex.insert(0, f"{len(files)} files selected")

    def browse_file(self, entry):
        f = filedialog.askopenfilename()
        if f:
            entry.delete(0, tk.END)
            entry.insert(0, f)

    def browse_folder(self, entry):
        f = filedialog.askdirectory()
        if f:
            entry.delete(0, tk.END)
            entry.insert(0, f)

    def run_extract(self):
        if not self.selected_bnks_extract:
            self.log("Error: Please select files using the Browse button.\n")
            return
            
        out = self.e_out_ex.get()
        if not out:
            self.log("Error: Please select an output folder.\n")
            return
            
        self.log_text.delete(1.0, tk.END)
        AudioEngine.extract_batch(self.selected_bnks_extract, out, self.log)

    def run_patch(self):
        bnk = self.e_bnk_pt.get()
        wem = self.e_wem_pt.get()
        self.log_text.delete(1.0, tk.END)
        AudioEngine.patch(bnk, wem, self.log)

if __name__ == "__main__":
    root = tk.Tk()
    app = EchoToolApp(root)
    root.mainloop()
