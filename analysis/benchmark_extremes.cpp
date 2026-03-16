/**
 * benchmark_extremes.cpp
 *
 * Benchmark Qiskit Aer simulation methods directly through the C++ interface.
 * Reads Qobj JSON files produced by benchmark_extremes.py, builds AER::Circuit
 * objects and AER::Config, then calls AER::controller_execute<AER::Controller>.
 *
 * ── PREREQUISITES ──────────────────────────────────────────────────────────
 *
 *  sudo apt install nlohmann-json3-dev libopenblas-dev
 *
 *  git clone https://github.com/Qiskit/qiskit-aer.git
 *  cd qiskit-aer && git checkout 0.17
 *
 * ── COMPILATION (from inside the qiskit-aer directory) ─────────────────────
 *
 *  export AER_SRC=$(pwd)/src
 *
 *  g++ -std=c++17 -O2 \
 *      -I${AER_SRC} \
 *      -I${AER_SRC}/third-party/spdlog/include \
 *      -DSPDLOG_ACTIVE_LEVEL=SPDLOG_LEVEL_OFF \
 *      -DAER_DISABLE_GDR \
 *      ../benchmark_extremes.cpp \
 *      -o benchmark_extremes \
 *      -lopenblas -lpthread
 *
 * ── USAGE ──────────────────────────────────────────────────────────────────
 *
 *  Run the Python script first to generate the Qobj JSON files:
 *    uv run python analysis/benchmark_extremes.py
 *
 *  Then (from the InferQ project root or anywhere):
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
#include <memory>
#include <sstream>
#include <string>
#include <sys/resource.h>
#include <vector>

// Aer headers (controller_execute.hpp is intentionally excluded — it pulls in
// pybind11 which is not needed for a standalone binary)
#include "controllers/aer_controller.hpp"
#include "framework/circuit.hpp"
#include "framework/config.hpp"
#include "framework/json.hpp"
#include "noise/noise_model.hpp"

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// Helper: read whole file into string
// ---------------------------------------------------------------------------
static std::string read_file(const fs::path &p)
{
    std::ifstream f(p);
    if (!f.is_open())
        throw std::runtime_error("Cannot open: " + p.string());
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

// ---------------------------------------------------------------------------
// Helper: peak RSS (KB) — macOS returns bytes, Linux returns KB
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
    std::string mode;
    double      wall_s{};
    long        rss_before_kb{};
    long        rss_after_kb{};
    bool        success{false};
    std::string status;
};

// ---------------------------------------------------------------------------
// Build AER::Config from the Qobj JSON "config" section
// ---------------------------------------------------------------------------
static AER::Config make_config(const json_t &qobj_cfg, const std::string &method, bool single_core)
{
    AER::Config cfg;

    cfg.method = method;

    if (qobj_cfg.contains("shots"))
        cfg.shots = qobj_cfg["shots"].get<uint_t>();

    if (qobj_cfg.contains("memory_slots"))
        cfg.memory_slots = qobj_cfg["memory_slots"].get<uint_t>();

    if (qobj_cfg.contains("n_qubits"))
        cfg.n_qubits.value(qobj_cfg["n_qubits"].get<uint_t>());

    if (single_core) {
        cfg.max_parallel_threads.value(1u);
        cfg.max_parallel_experiments.value(1u);
        cfg.max_parallel_shots.value(1u);
    }

    return cfg;
}

// ---------------------------------------------------------------------------
// Run one Qobj JSON file and time it
// ---------------------------------------------------------------------------
static BenchResult run_qobj(
    const std::string &circuit_label,
    const std::string &method,
    const std::string &mode,
    const fs::path    &json_path)
{
    BenchResult res;
    res.circuit = circuit_label;
    res.method  = method;
    res.mode    = mode;

    // Parse JSON
    json_t qobj;
    try {
        qobj = json_t::parse(read_file(json_path));
    } catch (const std::exception &e) {
        res.status = std::string("JSON parse error: ") + e.what();
        return res;
    }

    const json_t &qobj_cfg    = qobj["config"];
    const json_t &experiments  = qobj["experiments"];
    bool single_core = (mode == "single");

    // Build circuits
    std::vector<std::shared_ptr<AER::Circuit>> circuits;
    try {
        for (const auto &exp : experiments)
            circuits.push_back(std::make_shared<AER::Circuit>(exp, qobj_cfg));
    } catch (const std::exception &e) {
        res.status = std::string("Circuit build error: ") + e.what();
        return res;
    }

    AER::Config          config     = make_config(qobj_cfg, method, single_core);
    AER::Noise::NoiseModel noise_model; // empty — no noise

    // Prepare circuits (set_params + set_metadata + seed) — mirrors what
    // controller_execute<> does internally without needing pybind11
    uint_t seed = 42, seed_shift = 0;
    for (auto &circ : circuits) {
        circ->set_params(config.enable_truncation);
        circ->set_metadata(config, config.enable_truncation);
        circ->seed = seed + seed_shift;
        seed_shift += 2113;
    }

    res.rss_before_kb = peak_rss_kb();
    auto t_start = std::chrono::high_resolution_clock::now();

    try {
        AER::Controller controller;
        controller.set_config(config);
        AER::Result result = controller.execute(circuits, noise_model, config);

        auto t_end        = std::chrono::high_resolution_clock::now();
        res.wall_s        = std::chrono::duration<double>(t_end - t_start).count();
        res.rss_after_kb  = peak_rss_kb();

        res.success = (result.status == AER::Result::Status::completed);
        switch (result.status) {
            case AER::Result::Status::completed:       res.status = "COMPLETED";   break;
            case AER::Result::Status::partial_completed: res.status = "PARTIAL";   break;
            case AER::Result::Status::error:           res.status = "ERROR: " + result.message; break;
            default:                                   res.status = "UNKNOWN";     break;
        }

    } catch (const std::exception &e) {
        auto t_end       = std::chrono::high_resolution_clock::now();
        res.wall_s       = std::chrono::duration<double>(t_end - t_start).count();
        res.rss_after_kb = peak_rss_kb();
        res.status       = std::string("EXCEPTION: ") + e.what();
    }

    return res;
}

// ---------------------------------------------------------------------------
// Print formatted table
// ---------------------------------------------------------------------------
static void print_table(const std::vector<BenchResult> &results)
{
    const std::string sep(92, '-');
    std::cout << "\n" << sep << "\n"
              << std::left
              << std::setw(8)  << "circuit"
              << std::setw(26) << "method"
              << std::setw(8)  << "mode"
              << std::setw(12) << "wall_s"
              << std::setw(14) << "rss_delta_KB"
              << "ok\n"
              << sep << "\n";

    for (const auto &r : results) {
        long delta = r.rss_after_kb - r.rss_before_kb;
        std::cout << std::left
                  << std::setw(8)  << r.circuit
                  << std::setw(26) << r.method
                  << std::setw(8)  << r.mode
                  << std::fixed << std::setprecision(6)
                  << std::setw(12) << r.wall_s
                  << std::setw(14) << delta
                  << (r.success ? "YES" : "NO") << "\n";
        if (!r.success)
            std::cout << "         >> " << r.status << "\n";
    }
    std::cout << sep << "\n";
}

// ---------------------------------------------------------------------------
// Save full results CSV
// ---------------------------------------------------------------------------
static void save_csv(const std::vector<BenchResult> &results, const fs::path &out)
{
    std::ofstream f(out);
    f << "circuit,method,mode,wall_s,rss_delta_KB,success,status\n";
    for (const auto &r : results) {
        f << r.circuit << "," << r.method << "," << r.mode << ","
          << std::fixed << std::setprecision(6) << r.wall_s << ","
          << (r.rss_after_kb - r.rss_before_kb) << ","
          << (r.success ? "true" : "false") << ","
          << "\"" << r.status << "\"\n";
    }
    std::cout << "Results  -> " << out << "\n";
}

// ---------------------------------------------------------------------------
// Save summary CSV: one row per circuit+method, multi vs single side-by-side
// ---------------------------------------------------------------------------
static void save_summary_csv(const std::vector<BenchResult> &results, const fs::path &out)
{
    struct Pair { const BenchResult *multi = nullptr; const BenchResult *single = nullptr; };
    std::map<std::pair<std::string, std::string>, Pair> lookup;

    for (const auto &r : results) {
        auto key = std::make_pair(r.circuit, r.method);
        if (r.mode == "multi")  lookup[key].multi  = &r;
        if (r.mode == "single") lookup[key].single = &r;
    }

    // Preserve insertion order
    std::vector<std::pair<std::string, std::string>> order;
    for (const auto &r : results) {
        auto key = std::make_pair(r.circuit, r.method);
        if (std::find(order.begin(), order.end(), key) == order.end())
            order.push_back(key);
    }

    std::ofstream f(out);
    f << "circuit,method,wall_s_multi,rss_delta_KB_multi,wall_s_single,rss_delta_KB_single\n";

    for (const auto &key : order) {
        const auto &p = lookup[key];
        if (!p.multi || !p.single || !p.multi->success || !p.single->success)
            continue;
        f << key.first << "," << key.second << ","
          << std::fixed << std::setprecision(6)
          << p.multi->wall_s  << "," << (p.multi->rss_after_kb  - p.multi->rss_before_kb)  << ","
          << p.single->wall_s << "," << (p.single->rss_after_kb - p.single->rss_before_kb) << "\n";
    }
    std::cout << "Summary  -> " << out << "\n";
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
int main(int argc, char *argv[])
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

    const std::vector<std::string> labels  = {"win_1", "win_2", "lose_1", "lose_2"};
    const std::vector<std::string> methods = {"statevector", "density_matrix", "matrix_product_state"};
    const std::vector<std::string> modes   = {"multi", "single"};

    std::vector<BenchResult> all_results;

    for (const auto &label : labels) {
        std::cout << "\n=== Circuit: " << label << " ===\n";

        for (const auto &method : methods) {
            for (const auto &mode : modes) {

                fs::path json_path = data_dir / (label + "_" + method + "_" + mode + "_qobj.json");

                if (!fs::exists(json_path)) {
                    std::cerr << "  [SKIP] " << json_path.filename() << " not found\n";
                    continue;
                }

                auto res = run_qobj(label, method, mode, json_path);
                all_results.push_back(res);

                if (res.success) {
                    std::cout << "  [+] [" << std::left << std::setw(26) << method
                              << "][" << std::setw(6) << mode << "] "
                              << "wall=" << std::fixed << std::setprecision(4) << res.wall_s << "s  "
                              << "rss_delta=" << (res.rss_after_kb - res.rss_before_kb) << "KB\n";
                } else {
                    std::cout << "  [-] [" << std::left << std::setw(26) << method
                              << "][" << std::setw(6) << mode << "] " << res.status << "\n";
                }
            }
        }
    }

    print_table(all_results);

    save_csv(all_results,         data_dir / "benchmark_extremes_cpp_results.csv");
    save_summary_csv(all_results, data_dir / "benchmark_extremes_cpp_summary.csv");

    return 0;
}
