"""CLI: python extract_t1_t2_h.py sample.001 [more files] --json result.json."""
import argparse
import csv
import json
from pathlib import Path
import sys

from tma_app.t1_t2_h import extract_metrics, write_metric_plot


def main(argv=None):
    parser = argparse.ArgumentParser(description="按用户原版 v219 算法提取 T1、T2、H（原始 µm），不启动 GUI，不改源文件。")
    parser.add_argument("files", nargs="+", help="一个或多个 TA 数据文件；目录请配合 --recursive")
    parser.add_argument("--algorithm", choices=("super", "robust"), default="super")
    parser.add_argument("--sample-start", type=int, help="从第几个采样点开始，0 起算，包含")
    parser.add_argument("--sample-stop", type=int, help="到第几个采样点为止，0 起算，不包含")
    parser.add_argument("--recursive", action="store_true", help="递归读取目录中的数字扩展名和 .txt/.tai 文件")
    parser.add_argument("--json", type=Path, dest="json_path")
    parser.add_argument("--csv", type=Path, dest="csv_path")
    parser.add_argument("--plot-dir", type=Path, help="可选：按原脚本十字/两温度/高度箭头逻辑绘制 PNG（需要 matplotlib）")
    parser.add_argument("--quiet", action="store_true", help="控制台只显示成功数量与错误，完整结果仍写入指定 JSON/CSV")
    args = parser.parse_args(argv)
    paths = []
    for value in args.files:
        path = Path(value)
        if path.is_dir():
            if not args.recursive: parser.error("目录输入需要 --recursive")
            paths.extend(sorted(p for p in path.rglob("*") if p.is_file() and (p.suffix[1:].isdigit() or p.suffix.casefold() in (".txt", ".tai"))))
        else: paths.append(path)
    if not paths: parser.error("没有找到数据文件")
    inputs = {p.resolve() for p in paths}
    if any(p and p.resolve() in inputs for p in (args.json_path, args.csv_path)):
        parser.error("输出路径不能覆盖输入文件")
    if args.json_path and args.csv_path and args.json_path.resolve() == args.csv_path.resolve():
        parser.error("JSON 和 CSV 输出路径必须不同")
    results, errors = [], []
    if args.plot_dir: args.plot_dir.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(paths):
        try:
            metrics = extract_metrics(path, algorithm=args.algorithm, sample_start=args.sample_start, sample_stop=args.sample_stop)
            if args.plot_dir:
                plot = args.plot_dir / f"{index+1:03d}-{path.name}.png"
                if plot.resolve() in inputs: raise ValueError("绘图输出不能覆盖输入文件")
                write_metric_plot(path, metrics, plot); metrics["plot"] = str(plot)
            results.append(metrics)
        except Exception as exc: errors.append({"file": str(path), "error": str(exc)})
    report = {"results": results, "errors": errors}
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(payload, encoding="utf-8")
    if args.csv_path:
        fields = ["file", "sample", "T1", "T2", "H1", "H2", "H", "area", "algorithm", "sha256", "warnings", "error"]
        args.csv_path.parent.mkdir(parents=True, exist_ok=True)
        with args.csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fields, extrasaction="ignore"); writer.writeheader()
            writer.writerows(results); writer.writerows(errors)
    visible = {"files": len(results), "errors": errors} if args.quiet else report
    console = json.dumps(visible, ensure_ascii=False, indent=None if args.quiet else 2)
    try: console.encode(getattr(sys.stdout, "encoding", None) or "utf-8")
    except (UnicodeEncodeError, LookupError):
        console = json.dumps(visible, ensure_ascii=True, indent=None if args.quiet else 2)
    print(console)
    return 1 if errors else 0


if __name__ == "__main__": sys.exit(main())
