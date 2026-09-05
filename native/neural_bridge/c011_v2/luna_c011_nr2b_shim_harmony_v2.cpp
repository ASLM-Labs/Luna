#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include "llama.h"
#include "ggml-backend.h"

#include <algorithm>
#include <climits>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <vector>

struct luna_nr2b_api {
    HMODULE llama_module = nullptr;
    HMODULE ggml_module = nullptr;

    void (*backend_init)(void) = nullptr;
    void (*backend_free)(void) = nullptr;
    llama_model_params (*model_default_params)(void) = nullptr;
    llama_model * (*model_load_from_file)(const char *, llama_model_params) = nullptr;
    void (*model_free)(llama_model *) = nullptr;
    const llama_vocab * (*model_get_vocab)(const llama_model *) = nullptr;
    const char * (*model_chat_template)(const llama_model *, const char *) = nullptr;
    llama_context_params (*context_default_params)(void) = nullptr;
    llama_context * (*init_from_model)(llama_model *, llama_context_params) = nullptr;
    void (*context_free)(llama_context *) = nullptr;
    llama_memory_t (*get_memory)(const llama_context *) = nullptr;
    void (*memory_clear)(llama_memory_t, bool) = nullptr;
    int32_t (*chat_apply_template)(const char *, const llama_chat_message *, size_t, bool, char *, int32_t) = nullptr;
    int32_t (*tokenize)(const llama_vocab *, const char *, int32_t, llama_token *, int32_t, bool, bool) = nullptr;
    llama_batch (*batch_get_one)(llama_token *, int32_t) = nullptr;
    int32_t (*decode)(llama_context *, llama_batch) = nullptr;
    llama_sampler_chain_params (*sampler_chain_default_params)(void) = nullptr;
    llama_sampler * (*sampler_chain_init)(llama_sampler_chain_params) = nullptr;
    void (*sampler_chain_add)(llama_sampler *, llama_sampler *) = nullptr;
    llama_sampler * (*sampler_init_greedy)(void) = nullptr;
    llama_token (*sampler_sample)(llama_sampler *, llama_context *, int32_t) = nullptr;
    void (*sampler_free)(llama_sampler *) = nullptr;
    bool (*vocab_is_eog)(const llama_vocab *, llama_token) = nullptr;
    int32_t (*token_to_piece)(const llama_vocab *, llama_token, char *, int32_t, int32_t, bool) = nullptr;
    uint32_t (*n_ctx)(const llama_context *) = nullptr;
};

struct luna_nr2b_engine {
    luna_nr2b_api api;
    llama_model * model = nullptr;
    llama_context * ctx = nullptr;
    const llama_vocab * vocab = nullptr;
    llama_sampler * sampler = nullptr;
    bool backend_initialized = false;
};

static void set_error(char * buffer, size_t cap, const std::string & message) {
    if (buffer == nullptr || cap == 0) {
        return;
    }
    const size_t n = (std::min)(cap - 1, message.size());
    std::memcpy(buffer, message.data(), n);
    buffer[n] = '\0';
}

static std::string wide_to_utf8(const wchar_t * value) {
    if (value == nullptr) {
        return {};
    }
    const int required = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value, -1, nullptr, 0, nullptr, nullptr);
    if (required <= 0) {
        throw std::runtime_error("failed to convert Windows path to UTF-8");
    }
    std::string result(static_cast<size_t>(required), '\0');
    const int written = WideCharToMultiByte(
        CP_UTF8, WC_ERR_INVALID_CHARS, value, -1, result.data(), required, nullptr, nullptr
    );
    if (written != required) {
        throw std::runtime_error("failed to convert Windows path to UTF-8");
    }
    result.resize(static_cast<size_t>(required - 1));
    return result;
}

template <typename T>
static T load_symbol(HMODULE module, const char * name) {
    FARPROC proc = GetProcAddress(module, name);
    if (proc == nullptr) {
        throw std::runtime_error(std::string("missing native symbol: ") + name);
    }
    return reinterpret_cast<T>(proc);
}

static HMODULE load_absolute(const std::wstring & path) {
    HMODULE module = LoadLibraryW(path.c_str());
    if (module == nullptr) {
        throw std::runtime_error("LoadLibraryW failed for native runtime DLL");
    }
    return module;
}

static std::wstring join_path(const wchar_t * root, const wchar_t * leaf) {
    std::wstring result(root == nullptr ? L"" : root);
    if (!result.empty() && result.back() != L'\\' && result.back() != L'/') {
        result.push_back(L'\\');
    }
    result += leaf;
    return result;
}

static void unload_api(luna_nr2b_api & api) {
    if (api.llama_module != nullptr) {
        FreeLibrary(api.llama_module);
        api.llama_module = nullptr;
    }
    if (api.ggml_module != nullptr) {
        FreeLibrary(api.ggml_module);
        api.ggml_module = nullptr;
    }
}

static void destroy_engine(luna_nr2b_engine * engine) {
    if (engine == nullptr) {
        return;
    }
    if (engine->sampler != nullptr && engine->api.sampler_free != nullptr) {
        engine->api.sampler_free(engine->sampler);
        engine->sampler = nullptr;
    }
    if (engine->ctx != nullptr && engine->api.context_free != nullptr) {
        engine->api.context_free(engine->ctx);
        engine->ctx = nullptr;
    }
    if (engine->model != nullptr && engine->api.model_free != nullptr) {
        engine->api.model_free(engine->model);
        engine->model = nullptr;
    }
    if (engine->backend_initialized && engine->api.backend_free != nullptr) {
        engine->api.backend_free();
        engine->backend_initialized = false;
    }
    unload_api(engine->api);
    delete engine;
}

extern "C" __declspec(dllexport) uint32_t luna_nr2b_abi_version(void) {
    return 2u;
}

static int32_t luna_nr2b_engine_create_impl(
    const wchar_t * runtime_dir,
    const wchar_t * model_path,
    int32_t cpu_threads,
    uint32_t requested_ctx,
    uint32_t requested_batch,
    luna_nr2b_engine ** out_engine,
    char * error_buffer,
    size_t error_capacity
) {
    if (out_engine == nullptr) {
        set_error(error_buffer, error_capacity, "out_engine is null");
        return 2;
    }
    *out_engine = nullptr;

    try {
        if (runtime_dir == nullptr || model_path == nullptr) {
            throw std::runtime_error("runtime_dir/model_path is null");
        }
        if (
            cpu_threads < 1 ||
            requested_ctx < 64 ||
            requested_batch < 1 ||
            requested_batch > requested_ctx
        ) {
            throw std::runtime_error("invalid cpu_threads/requested_ctx/requested_batch");
        }

        if (!SetDllDirectoryW(runtime_dir)) {
            throw std::runtime_error("SetDllDirectoryW failed for CPU-only runtime staging");
        }

        std::unique_ptr<luna_nr2b_engine, void (*)(luna_nr2b_engine *)> engine(
            new luna_nr2b_engine(), destroy_engine
        );

        engine->api.ggml_module = load_absolute(join_path(runtime_dir, L"ggml.dll"));
        engine->api.llama_module = load_absolute(join_path(runtime_dir, L"llama.dll"));

        using backend_load_all_fn = void (*)(void);
        FARPROC backend_load = GetProcAddress(engine->api.ggml_module, "ggml_backend_load_all");

        engine->api.backend_init = load_symbol<void (*)(void)>(engine->api.llama_module, "llama_backend_init");
        engine->api.backend_free = load_symbol<void (*)(void)>(engine->api.llama_module, "llama_backend_free");
        engine->api.model_default_params =
            load_symbol<llama_model_params (*)(void)>(engine->api.llama_module, "llama_model_default_params");
        engine->api.model_load_from_file =
            load_symbol<llama_model * (*)(const char *, llama_model_params)>(
                engine->api.llama_module, "llama_model_load_from_file"
            );
        engine->api.model_free =
            load_symbol<void (*)(llama_model *)>(engine->api.llama_module, "llama_model_free");
        engine->api.model_get_vocab =
            load_symbol<const llama_vocab * (*)(const llama_model *)>(
                engine->api.llama_module, "llama_model_get_vocab"
            );
        engine->api.model_chat_template =
            load_symbol<const char * (*)(const llama_model *, const char *)>(
                engine->api.llama_module, "llama_model_chat_template"
            );
        engine->api.context_default_params =
            load_symbol<llama_context_params (*)(void)>(engine->api.llama_module, "llama_context_default_params");
        engine->api.init_from_model =
            load_symbol<llama_context * (*)(llama_model *, llama_context_params)>(
                engine->api.llama_module, "llama_init_from_model"
            );
        engine->api.context_free =
            load_symbol<void (*)(llama_context *)>(engine->api.llama_module, "llama_free");
        engine->api.get_memory =
            load_symbol<llama_memory_t (*)(const llama_context *)>(engine->api.llama_module, "llama_get_memory");
        engine->api.memory_clear =
            load_symbol<void (*)(llama_memory_t, bool)>(engine->api.llama_module, "llama_memory_clear");
        engine->api.chat_apply_template =
            load_symbol<int32_t (*)(const char *, const llama_chat_message *, size_t, bool, char *, int32_t)>(
                engine->api.llama_module, "llama_chat_apply_template"
            );
        engine->api.tokenize =
            load_symbol<int32_t (*)(const llama_vocab *, const char *, int32_t, llama_token *, int32_t, bool, bool)>(
                engine->api.llama_module, "llama_tokenize"
            );
        engine->api.batch_get_one =
            load_symbol<llama_batch (*)(llama_token *, int32_t)>(engine->api.llama_module, "llama_batch_get_one");
        engine->api.decode =
            load_symbol<int32_t (*)(llama_context *, llama_batch)>(engine->api.llama_module, "llama_decode");
        engine->api.sampler_chain_default_params =
            load_symbol<llama_sampler_chain_params (*)(void)>(
                engine->api.llama_module, "llama_sampler_chain_default_params"
            );
        engine->api.sampler_chain_init =
            load_symbol<llama_sampler * (*)(llama_sampler_chain_params)>(
                engine->api.llama_module, "llama_sampler_chain_init"
            );
        engine->api.sampler_chain_add =
            load_symbol<void (*)(llama_sampler *, llama_sampler *)>(
                engine->api.llama_module, "llama_sampler_chain_add"
            );
        engine->api.sampler_init_greedy =
            load_symbol<llama_sampler * (*)(void)>(engine->api.llama_module, "llama_sampler_init_greedy");
        engine->api.sampler_sample =
            load_symbol<llama_token (*)(llama_sampler *, llama_context *, int32_t)>(
                engine->api.llama_module, "llama_sampler_sample"
            );
        engine->api.sampler_free =
            load_symbol<void (*)(llama_sampler *)>(engine->api.llama_module, "llama_sampler_free");
        engine->api.vocab_is_eog =
            load_symbol<bool (*)(const llama_vocab *, llama_token)>(
                engine->api.llama_module, "llama_vocab_is_eog"
            );
        engine->api.token_to_piece =
            load_symbol<int32_t (*)(const llama_vocab *, llama_token, char *, int32_t, int32_t, bool)>(
                engine->api.llama_module, "llama_token_to_piece"
            );
        engine->api.n_ctx =
            load_symbol<uint32_t (*)(const llama_context *)>(engine->api.llama_module, "llama_n_ctx");

        engine->api.backend_init();
        engine->backend_initialized = true;

        if (backend_load != nullptr) {
            reinterpret_cast<backend_load_all_fn>(backend_load)();
        }

        llama_model_params model_params = engine->api.model_default_params();
        model_params.n_gpu_layers = 0;

        const std::string model_utf8 = wide_to_utf8(model_path);
        engine->model = engine->api.model_load_from_file(model_utf8.c_str(), model_params);
        if (engine->model == nullptr) {
            throw std::runtime_error("llama_model_load_from_file returned null");
        }

        engine->vocab = engine->api.model_get_vocab(engine->model);
        if (engine->vocab == nullptr) {
            throw std::runtime_error("llama_model_get_vocab returned null");
        }

        llama_context_params ctx_params = engine->api.context_default_params();
        ctx_params.n_ctx = requested_ctx;
        ctx_params.n_batch = requested_batch;
        ctx_params.n_threads = cpu_threads;
        ctx_params.n_threads_batch = cpu_threads;
        ctx_params.offload_kqv = false;
        ctx_params.op_offload = false;

        engine->ctx = engine->api.init_from_model(engine->model, ctx_params);
        if (engine->ctx == nullptr) {
            throw std::runtime_error("llama_init_from_model returned null");
        }

        llama_sampler_chain_params sampler_params = engine->api.sampler_chain_default_params();
        engine->sampler = engine->api.sampler_chain_init(sampler_params);
        if (engine->sampler == nullptr) {
            throw std::runtime_error("llama_sampler_chain_init returned null");
        }

        llama_sampler * greedy = engine->api.sampler_init_greedy();
        if (greedy == nullptr) {
            throw std::runtime_error("llama_sampler_init_greedy returned null");
        }
        engine->api.sampler_chain_add(engine->sampler, greedy);

        *out_engine = engine.release();
        return 0;
    }
    catch (const std::exception & exc) {
        set_error(error_buffer, error_capacity, exc.what());
        return 10;
    }
    catch (...) {
        set_error(error_buffer, error_capacity, "unknown native exception during engine_create");
        return 11;
    }
}

extern "C" __declspec(dllexport) int32_t luna_nr2b_engine_create(
    const wchar_t * runtime_dir,
    const wchar_t * model_path,
    int32_t cpu_threads,
    uint32_t requested_ctx,
    luna_nr2b_engine ** out_engine,
    char * error_buffer,
    size_t error_capacity
) {
    return luna_nr2b_engine_create_impl(
        runtime_dir,
        model_path,
        cpu_threads,
        requested_ctx,
        std::min<uint32_t>(requested_ctx, 512u),
        out_engine,
        error_buffer,
        error_capacity
    );
}

extern "C" __declspec(dllexport) int32_t luna_nr2b_engine_create_v2(
    const wchar_t * runtime_dir,
    const wchar_t * model_path,
    int32_t cpu_threads,
    uint32_t requested_ctx,
    uint32_t requested_batch,
    luna_nr2b_engine ** out_engine,
    char * error_buffer,
    size_t error_capacity
) {
    return luna_nr2b_engine_create_impl(
        runtime_dir,
        model_path,
        cpu_threads,
        requested_ctx,
        requested_batch,
        out_engine,
        error_buffer,
        error_capacity
    );
}

static int32_t luna_nr2b_generate_impl(
    luna_nr2b_engine * engine,
    const char * user_prompt_utf8,
    int32_t max_output_tokens,
    char * output_buffer,
    size_t output_capacity,
    size_t * output_size,
    uint64_t * input_tokens,
    uint64_t * output_tokens,
    uint64_t * total_tokens,
    bool usage_required,
    char * error_buffer,
    size_t error_capacity
) {
    if (output_size != nullptr) {
        *output_size = 0;
    }
    if (input_tokens != nullptr) {
        *input_tokens = 0;
    }
    if (output_tokens != nullptr) {
        *output_tokens = 0;
    }
    if (total_tokens != nullptr) {
        *total_tokens = 0;
    }

    try {
        if (engine == nullptr || user_prompt_utf8 == nullptr) {
            throw std::runtime_error("engine/user prompt is null");
        }
        if (output_buffer == nullptr || output_capacity < 2 || output_size == nullptr) {
            throw std::runtime_error("invalid output buffer");
        }
        if (
            usage_required &&
            (input_tokens == nullptr || output_tokens == nullptr || total_tokens == nullptr)
        ) {
            throw std::runtime_error("ABI v2 usage output is null");
        }
        if (max_output_tokens < 1 || max_output_tokens > 256) {
            throw std::runtime_error("max_output_tokens outside proof bounds");
        }

        engine->api.memory_clear(engine->api.get_memory(engine->ctx), true);

        const char * tmpl = engine->api.model_chat_template(engine->model, nullptr);
        if (tmpl == nullptr || tmpl[0] == '\0') {
            set_error(error_buffer, error_capacity, "CHAT_TEMPLATE_MISSING");
            return 20;
        }

        llama_chat_message chat[1] = {
            {"user", user_prompt_utf8}
        };

        int32_t capacity = static_cast<int32_t>(std::max<size_t>(4096, std::strlen(user_prompt_utf8) * 4 + 1024));
        std::vector<char> rendered(static_cast<size_t>(capacity));

        int32_t rendered_len = engine->api.chat_apply_template(
            tmpl, chat, 1, true, rendered.data(), capacity
        );
        if (rendered_len < 0) {
            set_error(error_buffer, error_capacity, "CHAT_TEMPLATE_UNSUPPORTED_BY_LLAMA_C_API");
            return 21;
        }
        if (rendered_len >= capacity) {
            capacity = rendered_len + 1;
            rendered.assign(static_cast<size_t>(capacity), '\0');
            rendered_len = engine->api.chat_apply_template(
                tmpl, chat, 1, true, rendered.data(), capacity
            );
            if (rendered_len < 0 || rendered_len >= capacity) {
                set_error(error_buffer, error_capacity, "CHAT_TEMPLATE_RENDER_RETRY_FAILED");
                return 22;
            }
        }

        const int32_t token_need = engine->api.tokenize(
            engine->vocab, rendered.data(), rendered_len, nullptr, 0, true, true
        );
        if (token_need == INT32_MIN) {
            throw std::runtime_error("tokenization size overflow");
        }
        const int32_t prompt_token_count = token_need < 0 ? -token_need : token_need;
        if (prompt_token_count <= 0) {
            throw std::runtime_error("tokenization produced no prompt tokens");
        }

        std::vector<llama_token> prompt_tokens(static_cast<size_t>(prompt_token_count));
        const int32_t tokenized = engine->api.tokenize(
            engine->vocab,
            rendered.data(),
            rendered_len,
            prompt_tokens.data(),
            prompt_token_count,
            true,
            true
        );
        if (tokenized < 0) {
            throw std::runtime_error("prompt tokenization failed");
        }
        prompt_tokens.resize(static_cast<size_t>(tokenized));

        const uint32_t actual_ctx = engine->api.n_ctx(engine->ctx);
        if (prompt_tokens.size() + static_cast<size_t>(max_output_tokens) > actual_ctx) {
            throw std::runtime_error("prompt + output proof bound exceeds actual context");
        }

        llama_batch batch = engine->api.batch_get_one(
            prompt_tokens.data(), static_cast<int32_t>(prompt_tokens.size())
        );

        std::string output;
        output.reserve(4096);
        uint64_t generated_token_count = 0;

        llama_token next_token = 0;

        for (int32_t step = 0; step < max_output_tokens; ++step) {
            const int32_t decode_rc = engine->api.decode(engine->ctx, batch);
            if (decode_rc != 0) {
                throw std::runtime_error("llama_decode returned non-zero");
            }

            const llama_token token = engine->api.sampler_sample(engine->sampler, engine->ctx, -1);
            if (engine->api.vocab_is_eog(engine->vocab, token)) {
                break;
            }
            ++generated_token_count;

            char piece_stack[512];
            int32_t piece_len = engine->api.token_to_piece(
                engine->vocab, token, piece_stack, static_cast<int32_t>(sizeof(piece_stack)), 0, true
            );

            if (piece_len < 0) {
                const int32_t required = -piece_len;
                std::vector<char> dynamic_piece(static_cast<size_t>(required));
                piece_len = engine->api.token_to_piece(
                    engine->vocab, token, dynamic_piece.data(), required, 0, true
                );
                if (piece_len < 0) {
                    throw std::runtime_error("llama_token_to_piece failed after resize");
                }
                output.append(dynamic_piece.data(), static_cast<size_t>(piece_len));
            }
            else {
                output.append(piece_stack, static_cast<size_t>(piece_len));
            }

            next_token = token;
            batch = engine->api.batch_get_one(&next_token, 1);
        }

        if (output.empty()) {
            set_error(error_buffer, error_capacity, "generation ended without renderable output");
            return 23;
        }
        if (output.size() + 1 > output_capacity) {
            set_error(error_buffer, error_capacity, "output buffer too small");
            return 24;
        }

        const uint64_t prompt_tokens_count = static_cast<uint64_t>(prompt_tokens.size());
        if (
            generated_token_count >
            (std::numeric_limits<uint64_t>::max)() - prompt_tokens_count
        ) {
            throw std::runtime_error("token usage total overflow");
        }

        std::memcpy(output_buffer, output.data(), output.size());
        output_buffer[output.size()] = '\0';
        *output_size = output.size();
        if (usage_required) {
            *input_tokens = prompt_tokens_count;
            *output_tokens = generated_token_count;
            *total_tokens = prompt_tokens_count + generated_token_count;
        }
        return 0;
    }
    catch (const std::exception & exc) {
        set_error(error_buffer, error_capacity, exc.what());
        return 30;
    }
    catch (...) {
        set_error(error_buffer, error_capacity, "unknown native exception during generate");
        return 31;
    }
}

extern "C" __declspec(dllexport) int32_t luna_nr2b_generate(
    luna_nr2b_engine * engine,
    const char * user_prompt_utf8,
    int32_t max_output_tokens,
    char * output_buffer,
    size_t output_capacity,
    size_t * output_size,
    char * error_buffer,
    size_t error_capacity
) {
    return luna_nr2b_generate_impl(
        engine,
        user_prompt_utf8,
        max_output_tokens,
        output_buffer,
        output_capacity,
        output_size,
        nullptr,
        nullptr,
        nullptr,
        false,
        error_buffer,
        error_capacity
    );
}

extern "C" __declspec(dllexport) int32_t luna_nr2b_generate_v2(
    luna_nr2b_engine * engine,
    const char * user_prompt_utf8,
    int32_t max_output_tokens,
    char * output_buffer,
    size_t output_capacity,
    size_t * output_size,
    uint64_t * input_tokens,
    uint64_t * output_tokens,
    uint64_t * total_tokens,
    char * error_buffer,
    size_t error_capacity
) {
    return luna_nr2b_generate_impl(
        engine,
        user_prompt_utf8,
        max_output_tokens,
        output_buffer,
        output_capacity,
        output_size,
        input_tokens,
        output_tokens,
        total_tokens,
        true,
        error_buffer,
        error_capacity
    );
}

extern "C" __declspec(dllexport) void luna_nr2b_engine_destroy(luna_nr2b_engine * engine) {
    try {
        destroy_engine(engine);
    }
    catch (...) {
        // Destruction is best-effort at this proof boundary.
    }
}
