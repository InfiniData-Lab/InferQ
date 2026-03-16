/**
 * benchmark_extremes.cpp
 *
 * Benchmark Qiskit Aer simulation methods directly through the C++ interface.
 * Reads Qobj JSON files produced by benchmark_extremes.py and passes them to
 * AER::Controller, measuring wall time (std::chrono) and peak RSS memory
 * (getrusage).
 *
 * ── PREREQUISITES ──────────────────────────────────────────────────────────
 *
 *  1. Clone qiskit-aer at the same version used by the Python environment:
 *
 *       git clone https://github.com/Qiskit/qiskit-aer.git
 *       cd qiskit-aer && git checkout 0.17
 *
 *  2. Install its C++ dependencies (OpenBLAS / Accelerate, LAPACK, spdlog).
 *     On macOS with Homebrew:
 *       brew install openblas spdlog nlohmann-json
 *
 * ── COMPILATION ────────────────────────────────────────────────────────────
 *
 *  Set AER_SRC to the cloned repo's src/ directory, then:
 *
 *  macOS (Accelerate):
 *    g++ -std=c++17 -O2 \
 *        -I${AER_SRC} \
 *        -I${AER_SRC}/third-party/spdlog/include \
 *        -I${AER_SRC}/third-party/nlohmann \
 *        -I${AER_SRC}/third-party/pybind11/include \
 *        -DSPDLOG_ACTIVE_LEVEL=SPDLOG_LEVEL_OFF \
 *        -DAER_DISABLE_GDR \
 *        benchmark_extremes.cpp \
 *        -o benchmark_extremes \
 *        -framework Accelerate
 *
 *  Linux (OpenBLAS):
 *    g++ -std=c++17 -O2 \
 *        -I${AER_SRC} \
 *        -I${AER_SRC}/third-party/spdlog/include \
 *        -I${AER_SRC}/third-party/nlohmann \
 *        -DSPDLOG_ACTIVE_LEVEL=SPDLOG_LEVEL_OFF \
 *        -DAER_DISABLE_GDR \
 *        benchmark_extremes.cpp \
 *        -o benchmark_extremes \
 *        -lopenblas -lpthread
 *
 * ── USAGE ──────────────────────────────────────────────────────────────────
 *
 *  Run the Python script first to generate the Qobj JSON files:
 *    uv run python analysis/benchmark_extremes.py
 *
 *  Then:
 *    ./benchmark_extremes path/to/data/extremes/
 *
 * ───────────────────────────────────────────────────────────────────────────
 */

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <sys/resource.h>
#include <vector>

// nlohmann/json – exposed via qiskit-aer's framework wrapper
#include "framework/json.hpp"

// Aer C++ controller – the single entry-point for all simulation methods
#include "controllers/aer_controller.hpp"

namespace fs = std::filesystem;
using json   = nlohmann::json;

// ---------------------------------------------------------------------------
// Helper: read a whole file into a string
// ---------------------------------------------------------------------------
static std::string read_file(const fs::path& p)
{
    std::ifstream f(p);
    if (!f.is_open())
        throw std::runtime_error("Cannot open: " + p.string());
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

// ---------------------------------------------------------------------------
// Helper: peak RSS since process start (KB)
//   macOS: ru_maxrss is bytes; Linux: ru_maxrss is kilobytes
// ---------------------------------------------------------------------------
static long peak_rss_kb()
{
    struct rusage u{};
    getrusage(RUSAGE_SELF, &u);
#ifdef __APPLE__
    return u.ru_maxrss / 1024;
#else
    return u.ru_maxrss;
#endif
}

// ---------------------------------------------------------------------------
// Result of one benchmark run
// ---------------------------------------------------------------------------
struct BenchResult {
    std::string circuit;
    std::string method;
    std::string mode;       // "multi" | "single"
    double      wall_s{};
    long        rss_before_kb{};
    long        rss_after_kb{};
    bool        success{false};
    std::string status;
};

// ---------------------------------------------------------------------------
// Run one Qobj JSON string through AerController and time it
// ---------------------------------------------------------------------------
static BenchResult run_qobj(
    const std::string& circuit_label,
    const std::string& method,
    const std::string& mode,
    const std::string& qobj_str)
{
    BenchResult res;
    res.circuit = circuit_label;
    res.method  = method;
    res.mode    = mode;

    res.rss_before_kb = peak_rss_kb();

    auto t_start = std::chrono::high_resolution_clock::now();

    try {
        // AER::Controller::execute() accepts the Qobj JSON as a string
        // and returns a JSON-serialised Result.
        AER::Controller controller;
        std::string result_str = controller.execute(qobj_str);

        auto t_end   = std::chrono::high_resolution_clock::now();
        res.wall_s   = std::chrono::duration<double>(t_end - t_start).count();
        res.rss_after_kb = peak_rss_kb();

        // Parse result to check success
        auto result_json = json::parse(result_str);

        // The top-level status field and per-experiment success flags
        std::string top_status = result_json.value("status", "UNKNOWN");
        bool exp_ok = true;
        if (result_json.contains("results") && result_json["results"].is_array()) {
            for (auto& exp : result_json["results"]) {
                if (!exp.value("success", false)) {
                    exp_ok = false;
                    break;
                }
            }
        }

        res.success = (top_status == "COMPLETED" || top_status == "PARTIAL COMPLETED")
                      && exp_ok;
        res.status  = top_status;

    } catch (const std::exception& e) {
        auto t_end   = std::chrono::high_resolution_clock::now();
        res.wall_s   = std::chrono::duration<double>(t_end - t_start).count();
        res.rss_after_kb = peak_rss_kb();
        res.success  = false;
        res.status   = std::string("EXCEPTION: ") + e.what();
    }

    return res;
}

// ---------------------------------------------------------------------------
// Print a formatted table of results
// ---------------------------------------------------------------------------
static void print_table(const std::vector<BenchResult>& results)
{
    const std::string sep(95, '-');
    std::cout << "\n" << sep << "\n"
              << std::left
              << std::setw(8)  << "circuit"
              << std::setw(26) << "method"
              << std::setw(8)  << "mode"
              << std::setw(12) << "wall_s"
              << std::setw(14) << "rss_delta_KB"
              << std::setw(8)  << "ok"
              << "\n" << sep << "\n";

    for (const auto& r : results) {
        long rss_delta = r.rss_after_kb - r.rss_before_kb;

        std::cout << std::left
                  << std::setw(8)  << r.circuit
                  << std::setw(26) << r.method
                  << std::setw(8)  << r.mode
                  << std::fixed << std::setprecision(6)
                  << std::setw(12) << r.wall_s
                  << std::setw(14) << rss_delta
                  << std::setw(8)  << (r.success ? "YES" : "NO")
                  << "\n";

        if (!r.success)
            std::cout << "         " << r.status << "\n";
    }
    std::cout << sep << "\n";
}

// ---------------------------------------------------------------------------
// Save full results to CSV
// ---------------------------------------------------------------------------
static void save_csv(
    const std::vector<BenchResult>& results,
    const fs::path& out_path)
{
    std::ofstream f(out_path);
    f << "circuit,method,mode,wall_s,rss_delta_KB,success,status\n";
    for (const auto& r : results) {
        long rss_delta = r.rss_after_kb - r.rss_before_kb;
        f << r.circuit   << ","
          << r.method    << ","
          << r.mode      << ","
          << std::fixed << std::setprecision(6) << r.wall_s << ","
          << rss_delta   << ","
          << (r.success ? "true" : "false") << ","
          << "\"" << r.status << "\"\n";
    }
    std::cout << "Results saved to " << out_path << "\n";
}

// ---------------------------------------------------------------------------
// Save summary CSV: one row per circuit+method, multi vs single side by side
// ---------------------------------------------------------------------------
static void save_summary_csv(
    const std::vector<BenchResult>& results,
    const fs::path& out_path)
{
    // Build a map: (circuit, method) -> {multi, single} result
    struct Pair { const BenchResult* multi = nullptr; const BenchResult* single = nullptr; };
    std::map<std::pair<std::string,std::string>, Pair> lookup;

    for (const auto& r : results) {
        auto key = std::make_pair(r.circuit, r.method);
        if (r.mode == "multi")  lookup[key].multi  = &r;
        if (r.mode == "single") lookup[key].single = &r;
    }

    std::ofstream f(out_path);
    f << "circuit,method,"
      << "wall_s_multi,rss_delta_KB_multi,"
      << "wall_s_single,rss_delta_KB_single\n";

    // Emit in the same order as results (first appearance of each key)
    std::vector<std::pair<std::string,std::string>> order;
    for (const auto& r : results) {
        auto key = std::make_pair(r.circuit, r.method);
        if (std::find(order.begin(), order.end(), key) == order.end())
            order.push_back(key);
    }

    for (const auto& key : order) {
        const auto& p = lookup[key];
        // Skip if either run failed or is missing
        if (!p.multi || !p.single || !p.multi->success || !p.single->success)
            continue;

        f << key.first << "," << key.second << ","
          << std::fixed << std::setprecision(6)
          << p.multi->wall_s  << ","
          << (p.multi->rss_after_kb  - p.multi->rss_before_kb)  << ","
          << p.single->wall_s << ","
          << (p.single->rss_after_kb - p.single->rss_before_kb) << "\n";
    }

    std::cout << "Summary saved to " << out_path << "\n";
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
int main(int argc, char* argv[])
{
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <data/extremes/dir>\n";
        return 1;
    }

    fs::path data_dir(argv[1]);
    if (!fs::is_directory(data_dir)) {
        std::cerr << "Not a directory: " << data_dir << "\n";
        return 1;
    }

    // Circuit labels (must match what benchmark_extremes.py exported)
    const std::vector<std::string> labels   = {"win_1", "win_2", "lose_1", "lose_2"};
    const std::vector<std::string> methods  = {"statevector", "density_matrix", "matrix_product_state"};
    const std::vector<std::string> modes    = {"multi", "single"};

    std::vector<BenchResult> all_results;

    for (const auto& label : labels) {
        std::cout << "\n=== Circuit: " << label << " ===\n";

        for (const auto& method : methods) {
            for (const auto& mode : modes) {

                fs::path json_path = data_dir / (label + "_" + method + "_" + mode + "_qobj.json");

                if (!fs::exists(json_path)) {
                    std::cerr << "  [SKIP] " << json_path.filename() << " not found\n";
                    continue;
                }

                std::string qobj_str;
                try {
                    qobj_str = read_file(json_path);
                } catch (const std::exception& e) {
                    std::cerr << "  [ERROR] " << e.what() << "\n";
                    continue;
                }

                auto res = run_qobj(label, method, mode, qobj_str);
                all_results.push_back(res);

                char mark = res.success ? '+' : '-';
                if (res.success) {
                    std::cout << "  [" << mark << "] ["
                              << std::left << std::setw(26) << method
                              << "][" << std::setw(6) << mode << "] "
                              << "wall=" << std::fixed << std::setprecision(4) << res.wall_s << "s  "
                              << "rss_delta=" << (res.rss_after_kb - res.rss_before_kb) << "KB\n";
                } else {
                    std::cout << "  [" << mark << "] ["
                              << std::left << std::setw(26) << method
                              << "][" << std::setw(6) << mode << "] "
                              << res.status << "\n";
                }
            }
        }
    }

    print_table(all_results);

    fs::path csv_out     = data_dir / "benchmark_extremes_cpp_results.csv";
    fs::path summary_out = data_dir / "benchmark_extremes_cpp_summary.csv";
    save_csv(all_results, csv_out);
    save_summary_csv(all_results, summary_out);

    return 0;
}
