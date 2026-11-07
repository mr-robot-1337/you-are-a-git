#!/usr/bin/env python3
"""
Zero-dependency Android APK builder & signer (v1 JAR + v2 APK Signature Scheme v2)
for GitQuest (com.gitquest.app), targeting Android 15 (API 35, minSdk 24).
"""

import base64
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import zlib


def uleb128(val: int) -> bytes:
    out = bytearray()
    while True:
        byte = val & 0x7F
        val >>= 7
        if val != 0:
            byte |= 0x80
        out.append(byte)
        if val == 0:
            break
    return bytes(out)


def align4(data: bytearray) -> None:
    while len(data) % 4 != 0:
        data.append(0)


def build_axml() -> bytes:
    """Build binary AndroidManifest.xml (AXML) targeting SDK 35 (minSdk 24)."""
    # Attribute names with android.R.attr resource IDs in strictly ascending ID order
    attr_res = [
        ("theme", 0x01010000),
        ("label", 0x01010001),
        ("icon", 0x01010002),
        ("name", 0x01010003),
        ("exported", 0x01010010),
        ("configChanges", 0x0101001F),
        ("minSdkVersion", 0x0101020C),
        ("versionCode", 0x0101021B),
        ("versionName", 0x0101021C),
        ("targetSdkVersion", 0x01010270),
        ("hardwareAccelerated", 0x010102D3),
    ]

    extra_strings = [
        "package",
        "android",
        "http://schemas.android.com/apk/res/android",
        "manifest",
        "com.gitquest.app",
        "1.0.0",
        "uses-sdk",
        "application",
        "GitQuest",
        "activity",
        "com.gitquest.app.MainActivity",
        "intent-filter",
        "action",
        "android.intent.action.MAIN",
        "category",
        "android.intent.category.LAUNCHER",
    ]

    all_strings = [name for name, _ in attr_res] + extra_strings
    s_idx = {s: i for i, s in enumerate(all_strings)}

    # Build String Pool Chunk (RES_STRING_POOL_TYPE = 0x0001)
    encoded_strings = []
    offsets = []
    cur_offset = 0
    for s in all_strings:
        offsets.append(cur_offset)
        raw = s.encode("utf-16le")
        entry = struct.pack("<H", len(s)) + raw + b"\x00\x00"
        encoded_strings.append(entry)
        cur_offset += len(entry)

    strings_blob = bytearray(b"".join(encoded_strings))
    align4(strings_blob)

    string_count = len(all_strings)
    strings_start = 28 + 4 * string_count
    sp_chunk_size = strings_start + len(strings_blob)
    sp_chunk = (
        struct.pack(
            "<HHIIIIII",
            0x0001,         # RES_STRING_POOL_TYPE
            28,             # header_size
            sp_chunk_size,  # chunk_size
            string_count,
            0,              # style_count
            0,              # flags (UTF-16LE)
            strings_start,
            0,              # styles_start
        )
        + b"".join(struct.pack("<I", o) for o in offsets)
        + bytes(strings_blob)
    )

    # Build Resource Map Chunk (RES_XML_RESOURCE_MAP_TYPE = 0x0180)
    res_ids = [rid for _, rid in attr_res]
    rm_chunk_size = 8 + 4 * len(res_ids)
    rm_chunk = struct.pack("<HHI", 0x0180, 8, rm_chunk_size) + b"".join(
        struct.pack("<I", rid) for rid in res_ids
    )

    ns_uri = s_idx["http://schemas.android.com/apk/res/android"]
    ns_prefix = s_idx["android"]
    NO_NS = 0xFFFFFFFF

    def start_ns(line: int = 1) -> bytes:
        return struct.pack("<HHIIIII", 0x0100, 16, 24, line, 0xFFFFFFFF, ns_prefix, ns_uri)

    def end_ns(line: int = 1) -> bytes:
        return struct.pack("<HHIIIII", 0x0101, 16, 24, line, 0xFFFFFFFF, ns_prefix, ns_uri)

    def attr_str(ns: int, name: str, val: str) -> bytes:
        v_i = s_idx[val]
        return struct.pack("<IIIHBBI", ns, s_idx[name], v_i, 8, 0, 0x03, v_i)

    def attr_int(ns: int, name: str, val: int, dtype: int = 0x10) -> bytes:
        return struct.pack("<IIIHBBI", ns, s_idx[name], 0xFFFFFFFF, 8, 0, dtype, val & 0xFFFFFFFF)

    def start_elem(tag: str, attrs: list[bytes], line: int = 1) -> bytes:
        chunk_size = 36 + 20 * len(attrs)
        header = struct.pack("<HHIII", 0x0102, 16, chunk_size, line, 0xFFFFFFFF)
        ext = struct.pack(
            "<IIHHHHHH",
            NO_NS,
            s_idx[tag],
            20,          # attributeStart
            20,          # attributeSize
            len(attrs),  # attributeCount
            0,           # idIndex
            0,           # classIndex
            0,           # styleIndex
        )
        return header + ext + b"".join(attrs)

    def end_elem(tag: str, line: int = 1) -> bytes:
        return struct.pack("<HHIIIII", 0x0103, 16, 24, line, 0xFFFFFFFF, NO_NS, s_idx[tag])

    xml_nodes = b"".join([
        start_ns(2),
        start_elem(
            "manifest",
            [
                attr_int(ns_uri, "versionCode", 1, 0x10),
                attr_str(ns_uri, "versionName", "1.0.0"),
                attr_str(NO_NS, "package", "com.gitquest.app"),
            ],
            2,
        ),
        start_elem(
            "uses-sdk",
            [
                attr_int(ns_uri, "minSdkVersion", 24, 0x10),
                attr_int(ns_uri, "targetSdkVersion", 35, 0x10),
            ],
            7,
        ),
        end_elem("uses-sdk", 9),
        start_elem(
            "application",
            [
                # @android:style/Theme.DeviceDefault.NoActionBar = 0x01030129
                attr_int(ns_uri, "theme", 0x01030129, 0x01),
                attr_str(ns_uri, "label", "GitQuest"),
                # @android:drawable/sym_def_app_icon = 0x01080093
                attr_int(ns_uri, "icon", 0x01080093, 0x01),
                attr_int(ns_uri, "hardwareAccelerated", 0xFFFFFFFF, 0x12),
            ],
            11,
        ),
        start_elem(
            "activity",
            [
                attr_str(ns_uri, "label", "GitQuest"),
                attr_str(ns_uri, "name", "com.gitquest.app.MainActivity"),
                attr_int(ns_uri, "exported", 0xFFFFFFFF, 0x12),
                # orientation (0x80) | keyboardHidden (0x20) | screenSize (0x400) = 0x04A0
                attr_int(ns_uri, "configChanges", 0x000004A0, 0x11),
            ],
            17,
        ),
        start_elem("intent-filter", [], 22),
        start_elem("action", [attr_str(ns_uri, "name", "android.intent.action.MAIN")], 23),
        end_elem("action", 23),
        start_elem("category", [attr_str(ns_uri, "name", "android.intent.category.LAUNCHER")], 24),
        end_elem("category", 24),
        end_elem("intent-filter", 25),
        end_elem("activity", 26),
        end_elem("application", 27),
        end_elem("manifest", 28),
        end_ns(28),
    ])

    body = sp_chunk + rm_chunk + xml_nodes
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def build_resources_arsc() -> bytes:
    """Build a minimal valid resources.arsc (RES_TABLE_TYPE = 0x0002) for com.gitquest.app."""
    # Empty global string pool (28 bytes)
    global_sp = struct.pack("<HHIIIIII", 0x0001, 28, 28, 0, 0, 0, 28, 0)
    type_sp = struct.pack("<HHIIIIII", 0x0001, 28, 28, 0, 0, 0, 28, 0)
    key_sp = struct.pack("<HHIIIIII", 0x0001, 28, 28, 0, 0, 0, 28, 0)

    pkg_name = "com.gitquest.app".encode("utf-16le")
    pkg_name_padded = pkg_name + b"\x00" * (256 - len(pkg_name))
    pkg_header_size = 288
    pkg_chunk_size = pkg_header_size + len(type_sp) + len(key_sp)

    pkg_header = (
        struct.pack("<HHI", 0x0200, pkg_header_size, pkg_chunk_size)
        + struct.pack("<I", 0x7F)
        + pkg_name_padded
        + struct.pack(
            "<IIIII",
            pkg_header_size,                  # typeStrings offset
            0,                                # lastPublicType
            pkg_header_size + len(type_sp),   # keyStrings offset
            0,                                # lastPublicKey
            0,                                # typeIdOffset
        )
    )
    pkg_chunk = pkg_header + type_sp + key_sp

    total_size = 12 + len(global_sp) + len(pkg_chunk)
    table_header = struct.pack("<HHII", 0x0002, 12, total_size, 1)
    return table_header + global_sp + pkg_chunk


def build_classes_dex() -> bytes:
    """Build valid classes.dex containing com.gitquest.app.MainActivity."""
    strings = sorted([
        "<init>",
        "L",
        "Landroid/app/Activity;",
        "Landroid/content/Context;",
        "Landroid/os/Bundle;",
        "Landroid/view/View;",
        "Landroid/webkit/WebSettings;",
        "Landroid/webkit/WebView;",
        "Landroid/webkit/WebViewClient;",
        "Lcom/gitquest/app/MainActivity;",
        "Ljava/lang/String;",
        "MainActivity.java",
        "V",
        "VL",
        "VZ",
        "Z",
        "canGoBack",
        "file:///android_asset/index.html",
        "getSettings",
        "goBack",
        "loadUrl",
        "onBackPressed",
        "onCreate",
        "setContentView",
        "setDomStorageEnabled",
        "setJavaScriptEnabled",
        "setWebViewClient",
        "webView",
    ])
    s_idx = {s: i for i, s in enumerate(strings)}

    type_descriptors = sorted([
        "Landroid/app/Activity;",
        "Landroid/content/Context;",
        "Landroid/os/Bundle;",
        "Landroid/view/View;",
        "Landroid/webkit/WebSettings;",
        "Landroid/webkit/WebView;",
        "Landroid/webkit/WebViewClient;",
        "Lcom/gitquest/app/MainActivity;",
        "Ljava/lang/String;",
        "V",
        "Z",
    ], key=lambda d: s_idx[d])
    t_idx = {d: i for i, d in enumerate(type_descriptors)}

    # Protos: (shorty, return_type, param_types_tuple)
    proto_defs = [
        ("L", "Landroid/webkit/WebSettings;", ()),
        ("V", "V", ()),
        ("VL", "V", ("Landroid/content/Context;",)),
        ("VL", "V", ("Landroid/os/Bundle;",)),
        ("VL", "V", ("Landroid/view/View;",)),
        ("VL", "V", ("Landroid/webkit/WebViewClient;",)),
        ("VL", "V", ("Ljava/lang/String;",)),
        ("VZ", "V", ("Z",)),
        ("Z", "Z", ()),
    ]
    proto_defs.sort(key=lambda p: (t_idx[p[1]], tuple(t_idx[x] for x in p[2])))
    p_idx = {(p[1], p[2]): i for i, p in enumerate(proto_defs)}

    # Fields: (class_desc, type_desc, name)
    field_defs = [
        ("Lcom/gitquest/app/MainActivity;", "Landroid/webkit/WebView;", "webView"),
    ]
    f_idx = {(f[0], f[2], f[1]): i for i, f in enumerate(field_defs)}

    # Methods: (class_desc, name, (ret_desc, params_tuple))
    method_defs = [
        ("Landroid/app/Activity;", "<init>", ("V", ())),
        ("Landroid/app/Activity;", "onBackPressed", ("V", ())),
        ("Landroid/app/Activity;", "onCreate", ("V", ("Landroid/os/Bundle;",))),
        ("Landroid/app/Activity;", "setContentView", ("V", ("Landroid/view/View;",))),
        ("Landroid/webkit/WebSettings;", "setDomStorageEnabled", ("V", ("Z",))),
        ("Landroid/webkit/WebSettings;", "setJavaScriptEnabled", ("V", ("Z",))),
        ("Landroid/webkit/WebView;", "<init>", ("V", ("Landroid/content/Context;",))),
        ("Landroid/webkit/WebView;", "canGoBack", ("Z", ())),
        ("Landroid/webkit/WebView;", "getSettings", ("Landroid/webkit/WebSettings;", ())),
        ("Landroid/webkit/WebView;", "goBack", ("V", ())),
        ("Landroid/webkit/WebView;", "loadUrl", ("V", ("Ljava/lang/String;",))),
        ("Landroid/webkit/WebView;", "setWebViewClient", ("V", ("Landroid/webkit/WebViewClient;",))),
        ("Landroid/webkit/WebViewClient;", "<init>", ("V", ())),
        ("Lcom/gitquest/app/MainActivity;", "<init>", ("V", ())),
        ("Lcom/gitquest/app/MainActivity;", "onBackPressed", ("V", ())),
        ("Lcom/gitquest/app/MainActivity;", "onCreate", ("V", ("Landroid/os/Bundle;",))),
    ]
    method_defs.sort(key=lambda m: (t_idx[m[0]], s_idx[m[1]], p_idx[m[2]]))
    m_idx = {(m[0], m[1], m[2]): i for i, m in enumerate(method_defs)}

    # --- Assemble Dalvik Bytecode ---
    # 1. <init>()V: registers=1, ins=1, outs=1
    m_activity_init = m_idx[("Landroid/app/Activity;", "<init>", ("V", ()))]
    insns_init = struct.pack("<HHHH", 0x1070, m_activity_init, 0x0000, 0x000E)
    code_init = struct.pack("<HHHHII", 1, 1, 1, 0, 0, len(insns_init) // 2) + insns_init

    # 2. onBackPressed()V: registers=2 (v0=temp, v1=this), ins=1, outs=1
    f_webview = f_idx[("Lcom/gitquest/app/MainActivity;", "webView", "Landroid/webkit/WebView;")]
    m_can_go_back = m_idx[("Landroid/webkit/WebView;", "canGoBack", ("Z", ()))]
    m_go_back = m_idx[("Landroid/webkit/WebView;", "goBack", ("V", ()))]
    m_super_back = m_idx[("Landroid/app/Activity;", "onBackPressed", ("V", ()))]
    # 0000: iget-object v0, v1, webView (0x54, B=1, A=0 -> 0x1054, field_idx) [2 units]
    # 0002: if-eqz v0, +10 (to 000c) (0x38, A=0 -> 0x0038, 0x000a) [2 units]
    # 0004: invoke-virtual {v0}, canGoBack (0x106e, m_can_go_back, 0x0000) [3 units]
    # 0007: move-result v0 (0x000a) [1 unit]
    # 0008: if-eqz v0, +4 (to 000c) (0x0038, 0x0004) [2 units]
    # 000a: invoke-virtual {v0}, ... wait v0 was overwritten by move-result!
    # Let's use registers=3 (v0=webView, v1=bool, v2=this)!
    insns_back = struct.pack(
        "<HHHHHHHHHHHHHHHH",
        0x2054, f_webview,       # 0000: iget-object v0, v2, webView
        0x0038, 0x000B,          # 0002: if-eqz v0, +11 (to 000d)
        0x106E, m_can_go_back, 0x0000,  # 0004: invoke-virtual {v0}, WebView.canGoBack()Z
        0x010A,                  # 0007: move-result v1
        0x0138, 0x0005,          # 0008: if-eqz v1, +5 (to 000d)
        0x106E, m_go_back, 0x0000,      # 000a: invoke-virtual {v0}, WebView.goBack()V
        0x000E,                  # 000d: return-void (wait: 000a + 3 = 000d! So branch target is 000e!)
        0x106F, m_super_back,    # Wait: let's fix exact offsets below
    )
    # Let's compute exact unit offsets for onBackPressed()V:
    # 0000 (2): iget-object v0, v2, f_webview
    # 0002 (2): if-eqz v0, +12 (-> 000e)
    # 0004 (3): invoke-virtual {v0}, m_can_go_back
    # 0007 (1): move-result v1
    # 0008 (2): if-eqz v1, +6 (-> 000e)
    # 000a (3): invoke-virtual {v0}, m_go_back
    # 000d (1): return-void
    # 000e (3): invoke-super {v2}, m_super_back
    # 0011 (1): return-void
    insns_back = struct.pack(
        "<HHHHHHHHHHHHHHHHHH",
        0x2054, f_webview,
        0x0038, 12,
        0x106E, m_can_go_back, 0x0000,
        0x010A,
        0x0138, 6,
        0x106E, m_go_back, 0x0000,
        0x000E,
        0x106F, m_super_back, 0x0002,
        0x000E,
    )
    code_back = struct.pack("<HHHHII", 3, 1, 1, 0, 0, len(insns_back) // 2) + insns_back

    # 3. onCreate(Landroid/os/Bundle;)V: registers=5 (v0, v1, v2 locals; v3=this, v4=bundle), ins=2, outs=2
    m_super_oncreate = m_idx[("Landroid/app/Activity;", "onCreate", ("V", ("Landroid/os/Bundle;",)))]
    t_webview = t_idx["Landroid/webkit/WebView;"]
    m_webview_init = m_idx[("Landroid/webkit/WebView;", "<init>", ("V", ("Landroid/content/Context;",)))]
    m_get_settings = m_idx[("Landroid/webkit/WebView;", "getSettings", ("Landroid/webkit/WebSettings;", ()))]
    m_set_js = m_idx[("Landroid/webkit/WebSettings;", "setJavaScriptEnabled", ("V", ("Z",)))]
    m_set_dom = m_idx[("Landroid/webkit/WebSettings;", "setDomStorageEnabled", ("V", ("Z",)))]
    t_wvclient = t_idx["Landroid/webkit/WebViewClient;"]
    m_wvclient_init = m_idx[("Landroid/webkit/WebViewClient;", "<init>", ("V", ()))]
    m_set_client = m_idx[("Landroid/webkit/WebView;", "setWebViewClient", ("V", ("Landroid/webkit/WebViewClient;",)))]
    m_set_content = m_idx[("Landroid/app/Activity;", "setContentView", ("V", ("Landroid/view/View;",)))]
    s_url = s_idx["file:///android_asset/index.html"]
    m_load_url = m_idx[("Landroid/webkit/WebView;", "loadUrl", ("V", ("Ljava/lang/String;",)))]

    insns_oncreate_words = [
        0x206F, m_super_oncreate, 0x0043,  # invoke-super {v3, v4}, Activity.onCreate(Bundle)V
        0x0022, t_webview,                 # new-instance v0, WebView
        0x2070, m_webview_init, 0x0030,    # invoke-direct {v0, v3}, WebView.<init>(Context)V
        0x305B, f_webview,                 # iput-object v0, v3, MainActivity.webView
        0x106E, m_get_settings, 0x0000,    # invoke-virtual {v0}, WebView.getSettings()WebSettings
        0x010C,                            # move-result-object v1
        0x1212,                            # const/4 v2, #1
        0x206E, m_set_js, 0x0021,          # invoke-virtual {v1, v2}, WebSettings.setJavaScriptEnabled(Z)V
        0x206E, m_set_dom, 0x0021,         # invoke-virtual {v1, v2}, WebSettings.setDomStorageEnabled(Z)V
        0x0122, t_wvclient,                # new-instance v1, WebViewClient
        0x1070, m_wvclient_init, 0x0001,   # invoke-direct {v1}, WebViewClient.<init>()V
        0x206E, m_set_client, 0x0010,      # invoke-virtual {v0, v1}, WebView.setWebViewClient(WebViewClient)V
        0x206E, m_set_content, 0x0003,     # invoke-virtual {v3, v0}, Activity.setContentView(View)V
        0x011A, s_url,                     # const-string v1, "file:///android_asset/index.html"
        0x206E, m_load_url, 0x0010,        # invoke-virtual {v0, v1}, WebView.loadUrl(String)V
        0x000E,                            # return-void
    ]
    insns_oncreate = struct.pack("<" + "H" * len(insns_oncreate_words), *insns_oncreate_words)
    code_oncreate = (
        struct.pack("<HHHHII", 5, 2, 2, 0, 0, len(insns_oncreate_words)) + insns_oncreate
    )

    # --- Calculate Fixed Section Offsets ---
    header_size = 0x70
    string_ids_off = header_size
    string_ids_size = len(strings) * 4

    type_ids_off = string_ids_off + string_ids_size
    type_ids_size = len(type_descriptors) * 4

    proto_ids_off = type_ids_off + type_ids_size
    proto_ids_size = len(proto_defs) * 12

    field_ids_off = proto_ids_off + proto_ids_size
    field_ids_size = len(field_defs) * 8

    method_ids_off = field_ids_off + field_ids_size
    method_ids_size = len(method_defs) * 8

    class_defs_off = method_ids_off + method_ids_size
    class_defs_size = 32  # 1 class

    data_off = class_defs_off + class_defs_size
    data_area = bytearray()

    # 1. type_list items (4-byte aligned)
    type_lists_off = data_off + len(data_area)
    param_tuples = []
    param_tuple_off = {}
    for _, _, params in proto_defs:
        if params and params not in param_tuple_off:
            align4(data_area)
            off = data_off + len(data_area)
            param_tuple_off[params] = off
            param_tuples.append(params)
            data_area.extend(struct.pack("<I", len(params)))
            for p_desc in params:
                data_area.extend(struct.pack("<H", t_idx[p_desc]))
            align4(data_area)

    # 2. code_item section (4-byte aligned)
    align4(data_area)
    code_items_off = data_off + len(data_area)
    code_init_off = data_off + len(data_area)
    data_area.extend(code_init)
    align4(data_area)
    code_back_off = data_off + len(data_area)
    data_area.extend(code_back)
    align4(data_area)
    code_oncreate_off = data_off + len(data_area)
    data_area.extend(code_oncreate)

    # 3. string_data_item section
    string_data_off = data_off + len(data_area)
    string_offsets = []
    for s in strings:
        string_offsets.append(data_off + len(data_area))
        raw = s.encode("utf-8")
        data_area.extend(uleb128(len(s)))
        data_area.extend(raw)
        data_area.append(0)

    # 4. class_data_item section
    class_data_off = data_off + len(data_area)
    m_main_init = m_idx[("Lcom/gitquest/app/MainActivity;", "<init>", ("V", ()))]
    m_main_back = m_idx[("Lcom/gitquest/app/MainActivity;", "onBackPressed", ("V", ()))]
    m_main_oncreate = m_idx[("Lcom/gitquest/app/MainActivity;", "onCreate", ("V", ("Landroid/os/Bundle;",)))]

    class_data = (
        uleb128(0)  # static_fields_size
        + uleb128(1)  # instance_fields_size
        + uleb128(1)  # direct_methods_size
        + uleb128(2)  # virtual_methods_size
        # instance_field[0]: webView (private = 0x0002)
        + uleb128(f_webview)
        + uleb128(0x0002)
        # direct_method[0]: <init> (public constructor = 0x10001)
        + uleb128(m_main_init)
        + uleb128(0x10001)
        + uleb128(code_init_off)
        # virtual_method[0]: onBackPressed (public = 0x0001)
        + uleb128(m_main_back)
        + uleb128(0x0001)
        + uleb128(code_back_off)
        # virtual_method[1]: onCreate (protected = 0x0004) — delta from m_main_back
        + uleb128(m_main_oncreate - m_main_back)
        + uleb128(0x0004)
        + uleb128(code_oncreate_off)
    )
    data_area.extend(class_data)

    # 5. map_list section (4-byte aligned)
    align4(data_area)
    map_off = data_off + len(data_area)
    map_items = [
        (0x0000, 1, 0),
        (0x0001, len(strings), string_ids_off),
        (0x0002, len(type_descriptors), type_ids_off),
        (0x0003, len(proto_defs), proto_ids_off),
        (0x0004, len(field_defs), field_ids_off),
        (0x0005, len(method_defs), method_ids_off),
        (0x0006, 1, class_defs_off),
        (0x1001, len(param_tuples), type_lists_off),
        (0x2001, 3, code_items_off),
        (0x2002, len(strings), string_data_off),
        (0x2000, 1, class_data_off),
        (0x1000, 1, map_off),
    ]
    data_area.extend(struct.pack("<I", len(map_items)))
    for m_type, m_count, m_offset in map_items:
        data_area.extend(struct.pack("<HHII", m_type, 0, m_count, m_offset))

    file_size = data_off + len(data_area)
    data_size = len(data_area)

    # --- Build Fixed Tables ---
    string_ids_bytes = b"".join(struct.pack("<I", o) for o in string_offsets)
    type_ids_bytes = b"".join(struct.pack("<I", s_idx[d]) for d in type_descriptors)

    proto_ids_bytes = bytearray()
    for shorty, ret_t, params in proto_defs:
        p_off = param_tuple_off.get(params, 0)
        proto_ids_bytes.extend(struct.pack("<III", s_idx[shorty], t_idx[ret_t], p_off))

    field_ids_bytes = bytearray()
    for c_desc, t_desc, name in field_defs:
        field_ids_bytes.extend(struct.pack("<HHI", t_idx[c_desc], t_idx[t_desc], s_idx[name]))

    method_ids_bytes = bytearray()
    for c_desc, name, proto_key in method_defs:
        method_ids_bytes.extend(
            struct.pack("<HHI", t_idx[c_desc], p_idx[proto_key], s_idx[name])
        )

    class_defs_bytes = struct.pack(
        "<IIIIIIII",
        t_idx["Lcom/gitquest/app/MainActivity;"],  # class_idx
        0x0001,                                     # access_flags (ACC_PUBLIC)
        t_idx["Landroid/app/Activity;"],            # superclass_idx
        0,                                          # interfaces_off
        s_idx["MainActivity.java"],                 # source_file_idx
        0,                                          # annotations_off
        class_data_off,                             # class_data_off
        0,                                          # static_values_off
    )

    header_without_hashes = struct.pack(
        "<IIIIIIIIIIIIIIIIIIII",
        file_size,
        header_size,
        0x12345678,  # ENDIAN_CONSTANT
        0,           # link_size
        0,           # link_off
        map_off,
        len(strings),
        string_ids_off,
        len(type_descriptors),
        type_ids_off,
        len(proto_defs),
        proto_ids_off,
        len(field_defs),
        field_ids_off,
        len(method_defs),
        method_ids_off,
        1,
        class_defs_off,
        data_size,
        data_off,
    )

    body_after_sig = (
        header_without_hashes
        + string_ids_bytes
        + type_ids_bytes
        + bytes(proto_ids_bytes)
        + bytes(field_ids_bytes)
        + bytes(method_ids_bytes)
        + class_defs_bytes
        + bytes(data_area)
    )

    sha1_sig = hashlib.sha1(body_after_sig).digest()
    adler_val = zlib.adler32(sha1_sig + body_after_sig) & 0xFFFFFFFF

    return b"dex\n035\x00" + struct.pack("<I", adler_val) + sha1_sig + body_after_sig


def create_v1_signature_files(entries: dict[str, bytes], key_pem: str, cert_pem: str) -> tuple[bytes, bytes, bytes]:
    """Create META-INF/MANIFEST.MF, META-INF/CERT.SF, and META-INF/CERT.RSA."""
    manifest_lines = [
        "Manifest-Version: 1.0",
        "Created-By: 1.0 (Android)",
        "",
    ]
    for name, content in entries.items():
        digest = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
        manifest_lines.append(f"Name: {name}")
        manifest_lines.append(f"SHA-256-Digest: {digest}")
        manifest_lines.append("")

    manifest_bytes = "\r\n".join(manifest_lines).encode("utf-8")
    main_digest = base64.b64encode(hashlib.sha256(manifest_bytes).digest()).decode("ascii")

    sf_lines = [
        "Signature-Version: 1.0",
        "Created-By: 1.0 (Android)",
        f"SHA-256-Digest-Manifest: {main_digest}",
        "",
    ]
    for name in entries:
        section = (
            f"Name: {name}\r\n"
            f"SHA-256-Digest: {base64.b64encode(hashlib.sha256(entries[name]).digest()).decode('ascii')}\r\n\r\n"
        ).encode("utf-8")
        sec_digest = base64.b64encode(hashlib.sha256(section).digest()).decode("ascii")
        sf_lines.append(f"Name: {name}")
        sf_lines.append(f"SHA-256-Digest: {sec_digest}")
        sf_lines.append("")

    sf_bytes = "\r\n".join(sf_lines).encode("utf-8")

    with tempfile.NamedTemporaryFile("wb", delete=False) as sf_tmp:
        sf_tmp.write(sf_bytes)
        sf_path = sf_tmp.name

    rsa_path = sf_path + ".rsa"
    try:
        subprocess.run(
            [
                "openssl", "cms", "-sign", "-binary", "-noattr",
                "-in", sf_path,
                "-signer", cert_pem,
                "-inkey", key_pem,
                "-outform", "DER",
                "-out", rsa_path,
                "-md", "sha256",
            ],
            check=True,
        )
        with open(rsa_path, "rb") as f:
            rsa_bytes = f.read()
    finally:
        for p in (sf_path, rsa_path):
            if os.path.exists(p):
                os.remove(p)

    return manifest_bytes, sf_bytes, rsa_bytes


def build_aligned_zip(file_list: list[tuple[str, bytes, bool]]) -> tuple[bytes, bytes, bytes]:
    """
    Build a ZIP archive where uncompressed entries (store=True) have their file data
    aligned on a 4-byte boundary. Returns (before_cd, central_dir, eocd).
    """
    local_chunks = bytearray()
    cd_chunks = bytearray()
    num_entries = len(file_list)

    for name, raw_data, store_uncompressed in file_list:
        name_bytes = name.encode("utf-8")
        crc = zlib.crc32(raw_data) & 0xFFFFFFFF
        uncomp_size = len(raw_data)

        if store_uncompressed:
            method = 0  # ZIP_STORED
            comp_data = raw_data
        else:
            method = 8  # ZIP_DEFLATED
            comp_obj = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
            comp_data = comp_obj.compress(raw_data) + comp_obj.flush()

        comp_size = len(comp_data)
        local_header_offset = len(local_chunks)

        # Calculate extra padding so data offset is a multiple of 4 for stored entries
        base_end = local_header_offset + 30 + len(name_bytes)
        if store_uncompressed:
            pad_len = (4 - (base_end % 4)) % 4
        else:
            pad_len = 0
        extra = b"\x00" * pad_len

        # Local file header (0x04034b50)
        local_header = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,           # version needed
            0,            # flags
            method,
            0,            # mod time
            0x21,         # mod date (1980-01-01)
            crc,
            comp_size,
            uncomp_size,
            len(name_bytes),
            len(extra),
        )
        local_chunks.extend(local_header)
        local_chunks.extend(name_bytes)
        local_chunks.extend(extra)
        local_chunks.extend(comp_data)

        # Central directory header (0x02014b50)
        cd_header = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,           # version made by
            20,           # version needed
            0,            # flags
            method,
            0,            # mod time
            0x21,         # mod date
            crc,
            comp_size,
            uncomp_size,
            len(name_bytes),
            0,            # extra field len in CD
            0,            # comment len
            0,            # disk number
            0,            # internal attrs
            0,            # external attrs
            local_header_offset,
        )
        cd_chunks.extend(cd_header)
        cd_chunks.extend(name_bytes)

    cd_offset = len(local_chunks)
    cd_size = len(cd_chunks)
    eocd = struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        0,
        0,
        num_entries,
        num_entries,
        cd_size,
        cd_offset,
        0,
    )
    return bytes(local_chunks), bytes(cd_chunks), eocd


def compute_apk_v2_digest(before_cd: bytes, cd: bytes, eocd: bytes) -> bytes:
    """Compute APK Signature Scheme v2 SHA-256 chunked digest over the 3 ZIP sections."""
    CHUNK_SIZE = 1024 * 1024
    chunk_digests = []
    chunk_count = 0

    for section in (before_cd, cd, eocd):
        offset = 0
        sec_len = len(section)
        while offset < sec_len:
            chunk = section[offset : offset + CHUNK_SIZE]
            h = hashlib.sha256()
            h.update(b"\xa5")
            h.update(struct.pack("<I", len(chunk)))
            h.update(chunk)
            chunk_digests.append(h.digest())
            chunk_count += 1
            offset += CHUNK_SIZE

    top = hashlib.sha256()
    top.update(b"\x5a")
    top.update(struct.pack("<I", chunk_count))
    for d in chunk_digests:
        top.update(d)
    return top.digest()


def lp(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


def build_apk_v2_signing_block(top_digest: bytes, key_pem: str, cert_der: bytes, pubkey_der: bytes) -> bytes:
    """Construct APK Signature Scheme v2 Signing Block (ID 0x7109871a)."""
    ALGO_RSA_PKCS1_V1_5_SHA256 = 0x0103

    digest_entry = struct.pack("<I", ALGO_RSA_PKCS1_V1_5_SHA256) + lp(top_digest)
    digests_seq = lp(lp(digest_entry))
    certs_seq = lp(lp(cert_der))
    additional_attrs = lp(b"")

    signed_data_raw = digests_seq + certs_seq + additional_attrs

    with tempfile.NamedTemporaryFile("wb", delete=False) as sd_tmp:
        sd_tmp.write(signed_data_raw)
        sd_path = sd_tmp.name

    sig_path = sd_path + ".sig"
    try:
        subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_pem, "-out", sig_path, sd_path],
            check=True,
        )
        with open(sig_path, "rb") as f:
            signature_bytes = f.read()
    finally:
        for p in (sd_path, sig_path):
            if os.path.exists(p):
                os.remove(p)

    sig_entry = struct.pack("<I", ALGO_RSA_PKCS1_V1_5_SHA256) + lp(signature_bytes)
    signatures_seq = lp(lp(sig_entry))

    signer = lp(signed_data_raw) + signatures_seq + lp(pubkey_der)
    v2_block_value = lp(lp(signer))
    v2_id = 0x7109871A

    pair_payload = struct.pack("<I", v2_id) + v2_block_value
    pairs = struct.pack("<Q", len(pair_payload)) + pair_payload

    # Pad block to a multiple of 4096 bytes using Verity Padding Block (ID 0x42726577)
    base_total = 8 + len(pairs) + 8 + 16
    rem = base_total % 4096
    if rem != 0:
        needed = 4096 - rem
        if needed < 12:
            needed += 4096
        pad_value_len = needed - 12
        pad_payload = struct.pack("<I", 0x42726577) + (b"\x00" * pad_value_len)
        pairs += struct.pack("<Q", len(pad_payload)) + pad_payload

    size_field = len(pairs) + 8 + 16
    return (
        struct.pack("<Q", size_field)
        + pairs
        + struct.pack("<Q", size_field)
        + b"APK Sig Block 42"
    )


def main() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html_src = os.path.join(repo_root, "public", "index.html")
    asset_dst_dir = os.path.join(repo_root, "android", "app", "src", "main", "assets")
    os.makedirs(asset_dst_dir, exist_ok=True)
    shutil.copyfile(html_src, os.path.join(asset_dst_dir, "index.html"))

    with open(html_src, "rb") as f:
        index_html_bytes = f.read()

    axml_bytes = build_axml()
    arsc_bytes = build_resources_arsc()
    dex_bytes = build_classes_dex()

    core_entries = {
        "AndroidManifest.xml": axml_bytes,
        "resources.arsc": arsc_bytes,
        "classes.dex": dex_bytes,
        "assets/index.html": index_html_bytes,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        key_pem = os.path.join(tmpdir, "debug.key.pem")
        cert_pem = os.path.join(tmpdir, "debug.cert.pem")
        cert_der_path = os.path.join(tmpdir, "debug.cert.der")
        pub_der_path = os.path.join(tmpdir, "debug.pub.der")

        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", key_pem,
                "-out", cert_pem,
                "-days", "10000",
                "-subj", "/CN=GitQuest Android Debug/O=GitQuest/C=US",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["openssl", "x509", "-in", cert_pem, "-outform", "DER", "-out", cert_der_path],
            check=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", key_pem, "-pubout", "-outform", "DER", "-out", pub_der_path],
            check=True,
        )

        with open(cert_der_path, "rb") as f:
            cert_der = f.read()
        with open(pub_der_path, "rb") as f:
            pubkey_der = f.read()

        mf_bytes, sf_bytes, rsa_bytes = create_v1_signature_files(core_entries, key_pem, cert_pem)

        zip_entries = [
            # resources.arsc MUST be uncompressed and 4-byte aligned for targetSdk >= 30
            ("resources.arsc", arsc_bytes, True),
            ("AndroidManifest.xml", axml_bytes, False),
            ("classes.dex", dex_bytes, False),
            ("assets/index.html", index_html_bytes, False),
            ("META-INF/MANIFEST.MF", mf_bytes, False),
            ("META-INF/CERT.SF", sf_bytes, False),
            ("META-INF/CERT.RSA", rsa_bytes, False),
        ]

        before_cd, cd, eocd = build_aligned_zip(zip_entries)
        top_digest = compute_apk_v2_digest(before_cd, cd, eocd)
        v2_signing_block = build_apk_v2_signing_block(top_digest, key_pem, cert_der, pubkey_der)

    new_cd_offset = len(before_cd) + len(v2_signing_block)
    eocd_updated = eocd[:16] + struct.pack("<I", new_cd_offset) + eocd[20:]

    final_apk = before_cd + v2_signing_block + cd + eocd_updated
    out_apk_path = os.path.join(repo_root, "gitquest-android.apk")
    with open(out_apk_path, "wb") as f:
        f.write(final_apk)

    print(f"Built signed APK: {out_apk_path} ({len(final_apk)} bytes)")


if __name__ == "__main__":
    main()
