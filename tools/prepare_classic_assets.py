"""Prepare compact, source-grounded classic UI resources for redistribution."""
from pathlib import Path
import csv
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/classic-reference"
DEST = ROOT / "tma_app/assets/classic"


def main():
    model = json.loads((SOURCE / "classic-ui.json").read_text(encoding="utf-8"))
    with (ROOT / "analysis/winua_ui_strings_en_zh.csv").open(encoding="utf-8-sig", newline="") as handle:
        translations = {row["text_en"].casefold(): row["text_zh"] for row in csv.DictReader(handle)}
    special = {
        "Analyze1": "Analyse", "Open1": "Open", "Reopen1": "Reopen", "Close1": "Close", "CloseAll1": "Close All",
        "RemoveAnalysis1": "Remove Analysis", "SaveAnalysis1": "Save Analysis", "AnalysisOnly1": "Analysis Only",
        "AnalysisAndData1": "Analysis and Data", "SaveSession1": "Save Session", "EditParamBlock1": "Edit Param Block",
        "MainOptions1": "Options", "ExportPDFFile1": "Export PDF File", "TTSSignals1": "TTS Signals",
        "LoginLogout1": "Login", "Copy3": "Copy", "FileInformation1": "File Information", "AddScaleBar1": "Add Scale Bar",
        "AdjustLastResult1": "Adjust Last Result", "MpxList1": "Multiplexed Signals", "AnalysisLogComment1": "Analysis Log Comment",
        "AuditTrailComment1": "Audit Trail Comment", "ManualRescale1": "Manual", "FullScaleAxis1": "Full Scale Axis",
        "FullScaleAll1": "Full Scale All", "InstrParams1": "Instrument Params", "XAxis1": "X Axis", "YAxis1": "Y Axis",
        "XTime1": "Time", "XTemp1": "Temperature", "XSignal1": "X Signal", "Y1": "Y1", "Y2": "Y2", "Y3": "Y3", "Y4": "Y4",
        "FullRangeLimits1": "Full Range", "CursorLimits1": "Graphic Limits", "TimeLimits1": "Time",
        "TemperatureLimits1": "Temperature", "CycleLimits1": "Cycle", "AutoConfigure1": "Auto Configure",
        "ManualSetup1": "Manual Setup", "Edit4": "Edit Overlay", "Copy4": "Copy Overlay", "Plotlegend1": "Plot Legend",
        "HideResults1": "Hide Results", "TempAtWeightPercent1": "Temp at Weight %", "TimeAtWeightPercent1": "Time at Weight %",
        "WeightAtTemp1": "Weight at Temp", "WeightAtTime1": "Weight at Time", "WeightLossTemp1": "Weight Loss Temp",
        "WeightLossTime1": "Weight Loss Time", "ManualLimits2": "Manual Limits", "GraphicLimits1": "Graphic Limits",
        "GraphicStart1": "Graphic Start", "GraphicFinish1": "Graphic Stop", "AlphaAtX1": "Alpha at X",
        "AlphaX1ToX21": "Alpha X1 to X2", "AlphaFitX1ToX21": "Alpha Fit X1 to X2", "DimensionChange1": "Dimension Change",
        "SigHorizontal1": "Sig Horizontal", "SigTangent1": "Sig Tangent", "PeakRunningIntegral1": "Running Integral",
        "LabelAtXY1": "Label at X,Y", "CurveValueAtX1": "Curve Value at X", "CurveValueAtY1": "Curve Value at Y",
        "Macro2": "Macro", "YAxis2": "Linear Y Transform", "XAxis2": "Linear X Transform", "BNone": "None",
        "ResultsReport1": "Report", "ResultsSpreadsheet1": "Spreadsheet", "ResultsOptions1": "Options",
        "DataTableReport1": "Report", "DataTableSpreadsheet1": "Spreadsheet", "New3": "New", "Edit2": "Edit",
        "NewFile1": "New File", "LoadFile1": "Load File", "SaveFile1": "Save File", "SaveFileAs1": "Save File As",
        "SingleStep1": "Single Step", "AboutUniversalAnalysis1": "About Universal Analysis", "HowTo1": "How To",
        "GettingStartedGuide1": "Getting Started Guide", "GraphOptions1": "Graph Options",
    }
    # Runtime-populated entries have no meaningful static captions; the Qt
    # shell supplies open-file and document lists from the current workspace.
    dynamic = re.compile(r"^(?:F|P|CV|M|MCopy|MOpen|MExecute|R|W|B)\d+$")

    def simplify(node):
        name, props = node["name"], node["props"]
        if dynamic.fullmatch(name):
            return None
        caption = props.get("Caption", "")
        if caption == "-":
            return {"name": name, "caption": "-", "children": []}
        english = special.get(name)
        if english is None:
            english = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", re.sub(r"\d+$", "", name))
        localized = translations.get(english.casefold(), english)
        if name == "AboutUniversalAnalysis1":
            localized = "关于 Universal Analysis / TMA Studio"
        item = {"name": name, "caption": localized, "english": english,
                "children": [c for n in node["children"] if (c := simplify(n)) is not None]}
        sc = props.get("ShortCut")
        if sc:
            key = sc & 255
            if 32 <= key <= 126:
                item["shortcut"] = ("Ctrl+" if sc & 16384 else "") + ("Shift+" if sc & 8192 else "") + ("Alt+" if sc & 32768 else "") + chr(key)
        return item

    menus = [simplify(n) for n in model["main_menu"]["children"]]
    flatten = {}
    def gather(node):
        flatten[node["name"]] = node
        for child in node["children"]:
            gather(child)
    for n in menus:
        gather(n)
    aliases = {
        "OpenDataFileButton": "Open1", "ReopenDataFileButton": "Reopen1", "CloseDataFileButton": "Close1", "CloseAllFilesButton": "CloseAll1",
        "RemoveSavedAnalysisButton": "RemoveAnalysis1", "SaveAnalysisOnlyButton": "AnalysisOnly1", "SaveAnalysisAndDataButton": "AnalysisAndData1",
        "SaveSessionButton": "SaveSession1", "EditParamBlockButton": "EditParamBlock1", "MainOptionsButton": "MainOptions1",
        "CopyButton": "Copy3", "CopyPlotButton": "Copy3", "SignalSelectionButton": "Signals1", "SpreadSheetViewButton": "SpreadsheetView1",
        "ExitProgramButton": "Exit1", "ManualRescaleButton": "ManualRescale1", "IntegratePeakLinearButton": "Linear1",
        "IntegrateLinearButton": "Linear1", "PeakMaximumButton": "PeakMax1", "SmoothCurveButton": "Smooth1",
        "AnnotatePlotButton": "Annotate1", "ParametersSameAsButton": "ParamsSameAs1",
        "SelectCurveButton": "Curve1", "OverlayAutoConfigureButton": "AutoConfigure1",
        "OverlayManualSetupButton": "ManualSetup1", "SignalMaximumButton": "SignalMax1",
        "GlassStepTransitionButton": "GlassTransition1", "ShiftCurveButton": "Shift1",
        "IntegrateSigHorizontalButton": "SigHorizontal1",
    }
    buttons = []
    for node in model["toolbar"]["children"]:
        props, name = node["props"], node["name"]
        menu = aliases.get(name, name.removesuffix("Button") + "1")
        image_index = props.get("ImageIndex")
        if image_index is None:
            continue
        buttons.append({"name": name, "menu": menu, "image_index": image_index,
                        "caption": flatten.get(menu, {}).get("caption", name),
                        "static_visible": props.get("Visible", True)})
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "icons").mkdir(exist_ok=True)
    for source in (SOURCE / "toolbar-icons").glob("icon-*.png"):
        shutil.copy2(source, DEST / "icons" / source.name.removeprefix("icon-"))
    (DEST / "ui.json").write_text(json.dumps({"evidence": model["evidence"], "menus": menus, "buttons": buttons}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(menus)} menus, {len(buttons)} buttons and 160 source glyphs")


if __name__ == "__main__":
    main()
