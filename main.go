package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/data/binding"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/layout"
	"fyne.io/fyne/v2/storage"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
)

// ==========================================
//              CONFIGURATION
// ==========================================

type Config struct {
	ToolPath         string `json:"tool_path"`
	DecoderPath      string `json:"decoder_path"`
	PatchWemDir      string `json:"patch_wem_dir"`
	PatchOutputDir   string `json:"patch_output_dir"`
	WavToolsDir      string `json:"wav_tools_dir"`
	ConvertInputDir  string `json:"convert_input_dir"`
	ConvertOutputDir string `json:"convert_output_dir"`
	FadeDuration     string `json:"fade_duration"`
	TrimStart        string `json:"trim_start"`
	TrimEnd          string `json:"trim_end"`
	// Tab Visibility
	ShowExtract      bool   `json:"show_extract"`
	ShowSequencer    bool   `json:"show_sequencer"`
	ShowConvert      bool   `json:"show_convert"`
	ShowPatch        bool   `json:"show_patch"`
}

type ConfigManager struct {
	ConfigFile string
	Data       Config
}

func NewConfigManager() *ConfigManager {
	baseDir, _ := os.Getwd()
	settingsDir := filepath.Join(baseDir, "Settings")
	os.MkdirAll(settingsDir, 0755)

	cm := &ConfigManager{
		ConfigFile: filepath.Join(settingsDir, "config.json"),
	}

	// Auto-Detect Tools
	autoSound2Wem := filepath.Join(baseDir, "Settings", "Sound2Wem.cmd")
	autoVgm := filepath.Join(baseDir, "Settings", "vgmstream", "vgmstream-cli.exe")
	if _, err := os.Stat(autoVgm); os.IsNotExist(err) {
		altVgm := filepath.Join(baseDir, "Settings", "vgstream", "vgmstream-cli.exe")
		if _, err := os.Stat(altVgm); err == nil {
			autoVgm = altVgm
		}
	}

	cm.Data = Config{
		ToolPath:         autoSound2Wem,
		DecoderPath:      autoVgm,
		PatchWemDir:      baseDir,
		PatchOutputDir:   baseDir,
		WavToolsDir:      baseDir,
		ConvertInputDir:  baseDir,
		ConvertOutputDir: baseDir,
		FadeDuration:     "1.5",
		TrimStart:        "0",
		TrimEnd:          "10",
		ShowExtract:      true,
		ShowSequencer:    true,
		ShowConvert:      true,
		ShowPatch:        true,
	}
	cm.Load()
	
	if _, err := os.Stat(autoSound2Wem); err == nil && cm.Data.ToolPath == "" { cm.Data.ToolPath = autoSound2Wem }
	if _, err := os.Stat(autoVgm); err == nil && cm.Data.DecoderPath == "" { cm.Data.DecoderPath = autoVgm }
	
	return cm
}

func (cm *ConfigManager) Load() {
	file, err := os.ReadFile(cm.ConfigFile)
	if err == nil { json.Unmarshal(file, &cm.Data) }
}

func (cm *ConfigManager) Save() {
	data, _ := json.MarshalIndent(cm.Data, "", "    ")
	os.WriteFile(cm.ConfigFile, data, 0644)
}

func (cm *ConfigManager) SetPath(key string, path string) {
	if path == "" { return }
	info, err := os.Stat(path)
	isDir := err == nil && info.IsDir()
	finalPath := path
	if strings.HasSuffix(key, "_dir") && !isDir { finalPath = filepath.Dir(path) }

	switch key {
	case "tool_path": cm.Data.ToolPath = finalPath
	case "decoder_path": cm.Data.DecoderPath = finalPath
	case "patch_wem_dir": cm.Data.PatchWemDir = finalPath
	case "patch_output_dir": cm.Data.PatchOutputDir = finalPath
	case "wav_tools_dir": cm.Data.WavToolsDir = finalPath
	case "convert_input_dir": cm.Data.ConvertInputDir = finalPath
	case "convert_output_dir": cm.Data.ConvertOutputDir = finalPath
	}
	cm.Save()
}

// ==========================================
//              CORE LOGIC
// ==========================================

func runCommand(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	if runtime.GOOS == "windows" { cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true} }
	return cmd.Run()
}

func getDuration(wavPath string) float64 {
	cmd := exec.Command("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", wavPath)
	if runtime.GOOS == "windows" { cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true} }
	out, err := cmd.Output()
	if err != nil { return 0.0 }
	dur, _ := strconv.ParseFloat(strings.TrimSpace(string(out)), 64)
	return dur
}

func generateSilence(outputPath string, duration float64) bool {
	cmd := []string{"-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", fmt.Sprintf("%f", duration), outputPath}
	return runCommand("ffmpeg", cmd...) == nil
}

func runConversion(toolPath, inputWav, outputWem, qualityFlag string) bool {
	var cmd *exec.Cmd
	if strings.HasSuffix(strings.ToLower(toolPath), ".cmd") || strings.HasSuffix(strings.ToLower(toolPath), ".bat") {
		args := []string{"/c", toolPath}
		if qualityFlag != "" { args = append(args, "--conversion:"+qualityFlag) }
		args = append(args, inputWav)
		cmd = exec.Command("cmd.exe", args...)
	} else {
		cmd = exec.Command(toolPath, "-encode", inputWav, outputWem)
	}
	if runtime.GOOS == "windows" { cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true} }
	err := cmd.Run()

	wemName := filepath.Base(outputWem)
	possibleLocs := []string{
		outputWem,
		filepath.Join(filepath.Dir(inputWav), wemName),
		filepath.Join(filepath.Dir(toolPath), wemName),
	}
	for _, loc := range possibleLocs {
		if _, err := os.Stat(loc); err == nil {
			if loc != outputWem {
				os.Remove(outputWem)
				os.Rename(loc, outputWem)
			}
			return true
		}
	}
	return err == nil && false
}

func runDecoding(decoderPath, inputWem, outputWav string) bool {
	if decoderPath == "" { return false }
	cmd := exec.Command(decoderPath, "-o", outputWav, inputWem)
	if runtime.GOOS == "windows" { cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true} }
	err := cmd.Run()
	if _, statErr := os.Stat(outputWav); statErr == nil && err == nil { return true }
	return false
}

func IsWwiseBank(path string) bool {
	f, err := os.Open(path)
	if err != nil { return false }
	defer f.Close()
	buf := make([]byte, 4096)
	n, err := f.Read(buf)
	if err != nil { return false }
	return bytes.Contains(buf[:n], []byte("BKHD"))
}

func parseBnk(bnkPath string, logFunc func(string)) ([]byte, int64, uint32, int64) {
	data, err := os.ReadFile(bnkPath)
	if err != nil {
		logFunc(fmt.Sprintf("Error reading file: %v\n", err))
		return nil, 0, 0, 0
	}
	startIndex := bytes.Index(data, []byte("BKHD"))
	if startIndex == -1 {
		logFunc(fmt.Sprintf("[WARN] %s: No 'BKHD' header found.\n", filepath.Base(bnkPath)))
		return nil, 0, 0, 0
	}
	offset := startIndex
	didxOffset := int64(-1); didxSize := uint32(0); dataOffset := int64(-1)
	for offset < len(data)-8 {
		chunkID := string(data[offset : offset+4])
		chunkSize := binary.LittleEndian.Uint32(data[offset+4 : offset+8])
		if chunkID == "DIDX" {
			didxOffset = int64(offset + 8); didxSize = chunkSize
		} else if chunkID == "DATA" {
			dataOffset = int64(offset + 8)
		}
		offset += 8 + int(chunkSize)
	}
	if didxOffset == -1 || dataOffset == -1 {
		logFunc(fmt.Sprintf("Error: %s invalid (Missing DIDX/DATA).\n", filepath.Base(bnkPath)))
		return nil, 0, 0, 0
	}
	return data, didxOffset, didxSize, dataOffset
}

// ==========================================
//              UI IMPLEMENTATION
// ==========================================

func main() {
	myApp := app.New()
	myWindow := myApp.NewWindow("Echo Audio Editor")
	myWindow.Resize(fyne.NewSize(900, 800))

	cfg := NewConfigManager()
	baseDir, _ := os.Getwd()
	bnkDir := filepath.Join(baseDir, "BNK")
	audioFilesDir := filepath.Join(baseDir, "AudioFiles")
	newWavDir := filepath.Join(baseDir, "NewWAVandWEMS")
	os.MkdirAll(bnkDir, 0755)
	os.MkdirAll(audioFilesDir, 0755)
	os.MkdirAll(newWavDir, 0755)

	// --- LOGGING ---
	logData := binding.NewString()
	logData.Set("System Log Initialized...\n")
	logEntry := widget.NewMultiLineEntry()
	logEntry.Wrapping = fyne.TextWrapWord
	logEntry.Disable()
	logEntry.Bind(logData) 
	logFunc := func(msg string) {
		fmt.Print(msg)
		current, _ := logData.Get()
		logData.Set(current + msg)
	}
	
	// UI Update Trigger
	uiTrigger := binding.NewBool()
	var uiAction func()
	uiTrigger.AddListener(binding.NewDataListener(func() {
		if val, _ := uiTrigger.Get(); val {
			if uiAction != nil { uiAction() }
			uiTrigger.Set(false)
		}
	}))
	runOnUI := func(f func()) { uiAction = f; uiTrigger.Set(true) }

	showHelp := func(title, content string) { dialog.ShowInformation(title, content, myWindow) }

	createBrowseRow := func(entry *widget.Entry, isDir bool, filterExts []string, key string) *fyne.Container {
		btn := widget.NewButtonWithIcon("", theme.FolderOpenIcon(), func() {
			if isDir {
				dialog.ShowFolderOpen(func(uri fyne.ListableURI, err error) {
					if uri != nil { entry.SetText(uri.Path()); cfg.SetPath(key, uri.Path()) }
				}, myWindow)
			} else {
				fd := dialog.NewFileOpen(func(r fyne.URIReadCloser, err error) {
					if r != nil { entry.SetText(r.URI().Path()); cfg.SetPath(key, r.URI().Path()) }
				}, myWindow)
				if len(filterExts) > 0 { fd.SetFilter(storageFilter(filterExts)) }
				fd.Show()
			}
		})
		return container.NewBorder(nil, nil, nil, btn, entry)
	}

	// ================= TAB DEFINITIONS =================

	// 1. EXTRACT
	bnkCheckGroup := widget.NewCheckGroup([]string{}, nil)
	bnkScroll := container.NewScroll(bnkCheckGroup)
	bnkScroll.SetMinSize(fyne.NewSize(0, 300))
	patchBnkSelect := widget.NewSelect([]string{}, nil)
	
	refreshBnks := func() {
		files, _ := ioutil.ReadDir(bnkDir)
		var names []string
		for _, f := range files { if !f.IsDir() { names = append(names, f.Name()) } }
		runOnUI(func() {
			if len(names) == 0 {
				names = append(names, "(No files found in BNK folder)")
				bnkCheckGroup.Disable(); patchBnkSelect.Disable()
			} else {
				bnkCheckGroup.Enable(); patchBnkSelect.Enable()
			}
			bnkCheckGroup.Options = names; bnkCheckGroup.Refresh()
			patchBnkSelect.Options = names; patchBnkSelect.Refresh()
		})
	}
	
	performExtraction := func(filesToExtract []string) {
		workList := make([]string, len(filesToExtract))
		copy(workList, filesToExtract)
		go func() {
			if len(workList) == 0 { logFunc("[ERROR] No files to extract.\n"); return }
			decoderPath := cfg.Data.DecoderPath
			if _, err := os.Stat(decoderPath); os.IsNotExist(err) { logFunc(fmt.Sprintf("[ERROR] vgmstream-cli.exe missing at %s\n", decoderPath)); return }
			for _, filename := range workList {
				bnkPath := filepath.Join(bnkDir, filename)
				if !IsWwiseBank(bnkPath) { logFunc(fmt.Sprintf("[SKIP] %s is not valid.\n", filename)); continue }
				bnkID := filename 
				if strings.HasSuffix(filename, ".bnk") { bnkID = strings.TrimSuffix(filename, ".bnk") }
				logFunc(fmt.Sprintf("Extracting: %s\n", filename))
				data, didx, size, payload := parseBnk(bnkPath, logFunc)
				if data == nil { continue }
				wemDir := filepath.Join(audioFilesDir, bnkID); wavDir := filepath.Join(audioFilesDir, bnkID+"_WAV")
				os.MkdirAll(wemDir, 0755); os.MkdirAll(wavDir, 0755)
				num := int(size)/12
				for i:=0; i<num; i++ {
					pos := int(didx)+(i*12); fid := binary.LittleEndian.Uint32(data[pos:pos+4]); foff := binary.LittleEndian.Uint32(data[pos+4:pos+8]); fsize := binary.LittleEndian.Uint32(data[pos+8:pos+12])
					wemPath := filepath.Join(wemDir, fmt.Sprintf("%d.wem", fid))
					os.WriteFile(wemPath, data[int64(payload)+int64(foff) : int64(payload)+int64(foff)+int64(fsize)], 0644)
					runDecoding(decoderPath, wemPath, filepath.Join(wavDir, fmt.Sprintf("%d.wav", fid)))
				}
				logFunc("Done.\n")
			}
			logFunc("Extraction Job Complete.\n")
		}()
	}
	btnRunExtract := widget.NewButtonWithIcon("Extract Selected", theme.MediaPlayIcon(), func() { performExtraction(bnkCheckGroup.Selected) })
	btnExtractAll := widget.NewButtonWithIcon("Extract All", theme.MediaFastForwardIcon(), func() { performExtraction(bnkCheckGroup.Options) })
	tabExtract := container.NewTabItem("Extract", container.NewVBox(widget.NewLabelWithStyle("BNK Files", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}), widget.NewButtonWithIcon("Refresh", theme.ViewRefreshIcon(), refreshBnks), widget.NewSeparator(), bnkScroll, layout.NewSpacer(), container.NewGridWithColumns(2, btnRunExtract, btnExtractAll)))

	// 2. SEQUENCER
	var seqFiles []string
	seqList := widget.NewList(func() int { return len(seqFiles) }, func() fyne.CanvasObject { return widget.NewLabel("T") }, func(i widget.ListItemID, o fyne.CanvasObject) { o.(*widget.Label).SetText(filepath.Base(seqFiles[i])) })
	btnAddSeq := widget.NewButton("+", func() { fd := dialog.NewFileOpen(func(r fyne.URIReadCloser, err error) { if r!=nil { seqFiles=append(seqFiles, r.URI().Path()); seqList.Refresh() } }, myWindow); fd.SetFilter(storageFilter([]string{".wav"})); fd.Show() })
	
	// NEW: Add Folder Button
	btnAddFolder := widget.NewButton("+ Folder", func() {
		dialog.ShowFolderOpen(func(uri fyne.ListableURI, err error) {
			if uri == nil { return }
			path := uri.Path()
			cfg.SetPath("wav_tools_dir", path)
			files, err := ioutil.ReadDir(path)
			if err != nil { logFunc(fmt.Sprintf("[ERROR] Reading dir: %v\n", err)); return }
			count := 0
			for _, f := range files {
				if !f.IsDir() && strings.HasSuffix(strings.ToLower(f.Name()), ".wav") {
					seqFiles = append(seqFiles, filepath.Join(path, f.Name()))
					count++
				}
			}
			seqList.Refresh()
			logFunc(fmt.Sprintf("Added %d WAV files.\n", count))
		}, myWindow)
	})

	btnRemSeq := widget.NewButton("-", func() { if len(seqFiles)>0 { seqFiles=seqFiles[:len(seqFiles)-1]; seqList.Refresh() } })
	btnMerge := widget.NewButton("Merge", func() {
		if len(seqFiles)<2 { return }
		dialog.ShowFileSave(func(uri fyne.URIWriteCloser, err error) {
			if uri!=nil {
				path:=uri.URI().Path(); uri.Close()
				go func() { 
					f,_:=os.Create("list.txt"); for _,p:=range seqFiles { f.WriteString(fmt.Sprintf("file '%s'\n", p)) }; f.Close()
					runCommand("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", path); os.Remove("list.txt"); logFunc("Merged.\n")
				}()
			}
		}, myWindow)
	})
	entryBig := widget.NewEntry(); entryFade := widget.NewEntry(); entryFade.SetText("1.5"); chFade := widget.NewCheck("Fade", nil); chFade.Checked=true; chEnc := widget.NewCheck("Encode", nil); chEnc.Checked=true
	btnSplit := widget.NewButton("Split & Encode", func() {
		go func() {
			out := newWavDir // Save to NewWAVandWEMS
			fade,_ := strconv.ParseFloat(entryFade.Text, 64); cur:=0.0
			for _, ref := range seqFiles {
				dur := getDuration(ref); wav := filepath.Join(out, filepath.Base(ref))
				args := []string{"-y", "-i", entryBig.Text, "-ss", fmt.Sprintf("%f", cur), "-t", fmt.Sprintf("%f", dur)}
				if chFade.Checked && dur > fade { args = append(args, "-af", fmt.Sprintf("afade=t=out:st=%f:d=%f", dur-fade, fade)) }
				args = append(args, "-ac", "1", "-ar", "22050", wav); runCommand("ffmpeg", args...)
				cur+=dur
				if chEnc.Checked { runConversion(cfg.Data.ToolPath, wav, filepath.Join(out, strings.Replace(filepath.Base(ref),".wav",".wem",1)), "Vorbis Quality Low") }
			}
			logFunc(fmt.Sprintf("Split Complete. Files in %s\n", out))
		}()
	})
	btnHelpSeq := widget.NewButtonWithIcon("", theme.QuestionIcon(), func() { showHelp("Help", "Sequencer Is Here to Rebuild A whole folder of wavs by splitting your custom wav and matching echo format") })
	tabWav := container.NewTabItem("Sequencer", container.NewHSplit(
		container.NewBorder(widget.NewLabel("Sequence"), container.NewHBox(btnAddSeq, btnAddFolder, btnRemSeq, layout.NewSpacer(), btnMerge), nil, nil, seqList),
		container.NewVBox(container.NewHBox(widget.NewLabel("Custom File"), layout.NewSpacer(), btnHelpSeq), widget.NewForm(widget.NewFormItem("Input", createBrowseRow(entryBig, false, []string{".wav"}, "wav_tools_dir")), widget.NewFormItem("Fade", entryFade)), container.NewHBox(chFade, chEnc), btnSplit),
	))

	// 3. CONVERT
	entryWavC := widget.NewEntry(); entryOutC := widget.NewEntry(); entryOutC.SetText(cfg.Data.ConvertOutputDir); var wavsC []string
	btnBrowseWC := widget.NewButtonWithIcon("", theme.FolderOpenIcon(), func() { fd:=dialog.NewFileOpen(func(r fyne.URIReadCloser, err error) { if r!=nil { wavsC=[]string{r.URI().Path()}; entryWavC.SetText("1 file") } }, myWindow); fd.SetFilter(storageFilter([]string{".wav"})); fd.Show() })
	btnConv := widget.NewButton("Convert", func() {
		go func() {
			os.MkdirAll(entryOutC.Text, 0755)
			for _, w := range wavsC { runConversion(cfg.Data.ToolPath, w, filepath.Join(entryOutC.Text, strings.Replace(filepath.Base(w),".wav",".wem",1)), "Vorbis Quality High") }
			logFunc("Convert Done.\n")
		}()
	})
	btnHelpConv := widget.NewButtonWithIcon("", theme.QuestionIcon(), func() { showHelp("Help", "Convert WAV to WEM using sound2wem.cmd, please note wwise launcher has to be installed") })
	tabConvert := container.NewTabItem("Convert", container.NewVBox(container.NewHBox(layout.NewSpacer(), btnHelpConv), widget.NewForm(widget.NewFormItem("WAVs", container.NewBorder(nil,nil,nil,btnBrowseWC,entryWavC)), widget.NewFormItem("Out", createBrowseRow(entryOutC, true, nil, "convert_output_dir"))), btnConv))

	// 4. PATCH
	entryWemDirP := widget.NewEntry(); entryWemDirP.SetText(cfg.Data.PatchWemDir); entryOutP := widget.NewEntry(); entryOutP.SetText(cfg.Data.PatchOutputDir)
	btnPatch := widget.NewButton("Rebuild", func() {
		go func() {
			if patchBnkSelect.Selected == "" { logFunc("Select a bank.\n"); return }
			out := entryOutP.Text; os.MkdirAll(out, 0755); avail := make(map[string]string)
			files, _ := ioutil.ReadDir(entryWemDirP.Text)
			for _, f := range files { if strings.HasSuffix(strings.ToLower(f.Name()), ".wem") { avail[strings.TrimSuffix(f.Name(), filepath.Ext(f.Name()))] = filepath.Join(entryWemDirP.Text, f.Name()) } }
			bnkName := patchBnkSelect.Selected; bnkPath := filepath.Join(bnkDir, bnkName)
			logFunc(fmt.Sprintf("Patching %s\n", bnkName))
			data, didx, size, payload := parseBnk(bnkPath, logFunc)
			if data != nil {
				num := int(size)/12
				for i:=0; i<num; i++ {
					pos := int(didx)+(i*12); fid := binary.LittleEndian.Uint32(data[pos:pos+4]); foff := binary.LittleEndian.Uint32(data[pos+4:pos+8]); max := binary.LittleEndian.Uint32(data[pos+8:pos+12])
					if wem, ok := avail[fmt.Sprintf("%d", fid)]; ok {
						nb, _ := os.ReadFile(wem)
						if len(nb) <= int(max) {
							abs := int64(payload)+int64(foff); copy(data[abs:], nb)
							if pad := int(max)-len(nb); pad > 0 { copy(data[abs+int64(len(nb)):], make([]byte, pad)) }
							binary.LittleEndian.PutUint32(data[pos+8:], uint32(len(nb))); logFunc(fmt.Sprintf("[OK] %d\n", fid))
						} else { logFunc(fmt.Sprintf("[FAIL] %d too big\n", fid)) }
					}
				}
				os.WriteFile(filepath.Join(out, bnkName), data, 0644); logFunc("Saved.\n")
			}
		}()
	})
	btnHelpPatch := widget.NewButtonWithIcon("", theme.QuestionIcon(), func() { showHelp("Help", "Patch new WEMs into BNK") })
	tabPatch := container.NewTabItem("Patch", container.NewVBox(container.NewHBox(layout.NewSpacer(), btnHelpPatch), widget.NewForm(widget.NewFormItem("Bank", patchBnkSelect), widget.NewFormItem("WEMs", createBrowseRow(entryWemDirP, true, nil, "patch_wem_dir")), widget.NewFormItem("Out", createBrowseRow(entryOutP, true, nil, "patch_output_dir"))), btnPatch))

	
	entryToolSettings := widget.NewEntry(); entryToolSettings.SetText(cfg.Data.ToolPath)
	entryVgmSettings := widget.NewEntry(); entryVgmSettings.SetText(cfg.Data.DecoderPath)
	
	chkExtract := widget.NewCheck("Show Extract", nil); chkExtract.Checked = cfg.Data.ShowExtract
	chkSeq := widget.NewCheck("Show Sequencer", nil); chkSeq.Checked = cfg.Data.ShowSequencer
	chkConv := widget.NewCheck("Show Convert", nil); chkConv.Checked = cfg.Data.ShowConvert
	chkPatch := widget.NewCheck("Show Patch", nil); chkPatch.Checked = cfg.Data.ShowPatch

	tabs := container.NewAppTabs()

	updateTabs := func() {
		var activeTabs []*container.TabItem
		if chkExtract.Checked { activeTabs = append(activeTabs, tabExtract) }
		if chkSeq.Checked { activeTabs = append(activeTabs, tabWav) }
		if chkConv.Checked { activeTabs = append(activeTabs, tabConvert) }
		if chkPatch.Checked { activeTabs = append(activeTabs, tabPatch) }
		runOnUI(func() {
			tabs.SetItems(activeTabs)
			if len(activeTabs) > 0 { tabs.SelectIndex(0) }
		})
	}

	openSettings := func() {
		w := myApp.NewWindow("Settings")
		w.Resize(fyne.NewSize(500, 400))
		form := widget.NewForm(
			widget.NewFormItem("Sound2Wem", createBrowseRow(entryToolSettings, false, []string{".cmd", ".exe"}, "tool_path")),
			widget.NewFormItem("vgmstream", createBrowseRow(entryVgmSettings, false, []string{".exe"}, "decoder_path")),
		)
		saveBtn := widget.NewButtonWithIcon("Save & Close", theme.DocumentSaveIcon(), func() {
			cfg.Data.ToolPath = entryToolSettings.Text
			cfg.Data.DecoderPath = entryVgmSettings.Text
			cfg.Data.ShowExtract = chkExtract.Checked
			cfg.Data.ShowSequencer = chkSeq.Checked
			cfg.Data.ShowConvert = chkConv.Checked
			cfg.Data.ShowPatch = chkPatch.Checked
			cfg.Save()
			updateTabs()
			w.Close()
		})
		w.SetContent(container.NewBorder(nil, saveBtn, nil, nil, container.NewVBox(widget.NewLabelWithStyle("Paths", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}), form, widget.NewSeparator(), widget.NewLabelWithStyle("Tab Visibility", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}), chkExtract, chkSeq, chkConv, chkPatch)))
		w.Show()
	}

	btnSettings := widget.NewButtonWithIcon("", theme.SettingsIcon(), openSettings)

	refreshBnks()
	updateTabs()
	
	// Layout
	logHeader := container.NewBorder(nil, nil, widget.NewLabel("System Log:"), btnSettings)
	logPanel := container.NewBorder(logHeader, nil, nil, nil, logEntry)
	mainSplit := container.NewVSplit(tabs, logPanel)
	mainSplit.SetOffset(0.7) //

	myWindow.SetContent(mainSplit)
	myWindow.ShowAndRun()
}

func storageFilter(exts []string) storage.FileFilter { return storage.NewExtensionFileFilter(exts) }