package lua

/*
#cgo CFLAGS: -I${SRCDIR}/../../third_party/luajit/src
#cgo LDFLAGS: ${SRCDIR}/../../third_party/luajit/src/libluajit.a -lm
#include <lua.h>
#include <lualib.h>
#include <lauxlib.h>
#include <stdlib.h>

// Wrappers for Lua macros that cgo cannot call directly
static int wrap_luaL_dostring(lua_State *L, const char *s) {
	return luaL_dostring(L, s);
}
static int wrap_luaL_dofile(lua_State *L, const char *fn) {
	return luaL_dofile(L, fn);
}
static void wrap_lua_setglobal(lua_State *L, const char *name) {
	lua_setglobal(L, name);
}
static void wrap_lua_getglobal(lua_State *L, const char *name) {
	lua_getglobal(L, name);
}
static void wrap_lua_pop(lua_State *L, int n) {
	lua_pop(L, n);
}
*/
import "C"

import (
	"fmt"
	"os"
	"regexp"
	"unsafe"
)

// State 封装 LuaJIT lua_State
type State struct {
	L *C.lua_State
}

// NewState 创建新的 LuaJIT 状态
func NewState() *State {
	L := C.luaL_newstate()
	if L == nil {
		panic("luaL_newstate failed")
	}
	C.luaL_openlibs(L)
	return &State{L: L}
}

// Close 销毁 Lua 状态
func (s *State) Close() {
	if s.L != nil {
		C.lua_close(s.L)
		s.L = nil
	}
}

// DoString 执行 Lua 代码字符串
func (s *State) DoString(code string) error {
	cs := C.CString(code)
	defer C.free(unsafe.Pointer(cs))
	if C.wrap_luaL_dostring(s.L, cs) != 0 {
		err := C.GoString(C.lua_tolstring(s.L, -1, nil))
		C.wrap_lua_pop(s.L, 1) // lua_pop(L, 1)
		return fmt.Errorf("lua: %s", err)
	}
	return nil
}

// DoFile 执行 Lua 文件
func (s *State) DoFile(path string) error {
	cs := C.CString(path)
	defer C.free(unsafe.Pointer(cs))
	if C.wrap_luaL_dofile(s.L, cs) != 0 {
		err := C.GoString(C.lua_tolstring(s.L, -1, nil))
		C.wrap_lua_pop(s.L, 1)
		return fmt.Errorf("lua: %s", err)
	}
	return nil
}

// PushGoFunc 注册 Go 函数到 Lua 全局表
// 使用 registry 存储 Go 闭包，通过 upvalue 索引回调
func (s *State) SetGlobalInt(name string, value int) {
	cname := C.CString(name)
	defer C.free(unsafe.Pointer(cname))
	C.lua_pushinteger(s.L, C.lua_Integer(value))
	C.wrap_lua_setglobal(s.L, cname)
}

// SetGlobalString 设置全局字符串
func (s *State) SetGlobalString(name string, value string) {
	cname := C.CString(name)
	defer C.free(unsafe.Pointer(cname))
	cval := C.CString(value)
	defer C.free(unsafe.Pointer(cval))
	C.lua_pushstring(s.L, cval)
	C.wrap_lua_setglobal(s.L, cname)
}

// GetGlobalInt 读取全局整数
func (s *State) GetGlobalInt(name string) (int, bool) {
	cname := C.CString(name)
	defer C.free(unsafe.Pointer(cname))
	C.wrap_lua_getglobal(s.L, cname)
	if C.lua_type(s.L, -1) != C.LUA_TNUMBER {
		C.wrap_lua_pop(s.L, 1)
		return 0, false
	}
	val := int(C.lua_tointeger(s.L, -1))
	C.wrap_lua_pop(s.L, 1)
	return val, true
}

func (s *State) LoadFilesWithDeps(paths []string) error {
	sorted, err := topoSort(paths)
	if err != nil {
		return err
	}
	s.ResetOwner()
	for _, p := range sorted {
		if err := s.DoFileSandboxed(p); err != nil {
			return err
		}
	}
	return nil
}

func topoSort(paths []string) ([]string, error) {
	type fileInfo struct {
		path     string
		provides []string
		depends  []string
	}

	declareRe := regexp.MustCompile(`declare_counter\(\s*"([^"]+)"`)
	declareCharRe := regexp.MustCompile(`declare_char\(\s*"([^"]+)"`)
	declareSkillRe := regexp.MustCompile(`declare_skill\([^,]+,\s*"([^"]+)"`)
	getRe := regexp.MustCompile(`get_counter\(\s*"([^"]+)"`)
	getCharRe := regexp.MustCompile(`get_char\(\s*"([^"]+)"`)
	getSkillRe := regexp.MustCompile(`get_skill\([^,]+,\s*"([^"]+)"`)

	files := make([]fileInfo, len(paths))
	for i, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			return nil, fmt.Errorf("read %s: %w", p, err)
		}
		src := string(data)
		fi := fileInfo{path: p}
		for _, m := range declareRe.FindAllStringSubmatch(src, -1) {
			fi.provides = append(fi.provides, "counter:"+m[1])
		}
		for _, m := range declareCharRe.FindAllStringSubmatch(src, -1) {
			fi.provides = append(fi.provides, "char:"+m[1])
		}
		for _, m := range declareSkillRe.FindAllStringSubmatch(src, -1) {
			fi.provides = append(fi.provides, "skill:"+m[1])
		}
		for _, m := range getRe.FindAllStringSubmatch(src, -1) {
			fi.depends = append(fi.depends, "counter:"+m[1])
		}
		for _, m := range getCharRe.FindAllStringSubmatch(src, -1) {
			fi.depends = append(fi.depends, "char:"+m[1])
		}
		for _, m := range getSkillRe.FindAllStringSubmatch(src, -1) {
			fi.depends = append(fi.depends, "skill:"+m[1])
		}
		files[i] = fi
	}

	provider := map[string]int{}
	for i, fi := range files {
		for _, sym := range fi.provides {
			provider[sym] = i
		}
	}

	n := len(files)
	inDeg := make([]int, n)
	edges := make([][]int, n)
	for i := range edges {
		edges[i] = nil
	}
	for i, fi := range files {
		seen := map[int]bool{}
		for _, sym := range fi.depends {
			j, ok := provider[sym]
			if ok && j != i && !seen[j] {
				seen[j] = true
				edges[j] = append(edges[j], i)
				inDeg[i]++
			}
		}
	}

	queue := make([]int, 0, n)
	for i := 0; i < n; i++ {
		if inDeg[i] == 0 {
			queue = append(queue, i)
		}
	}

	sorted := make([]string, 0, n)
	for head := 0; head < len(queue); head++ {
		idx := queue[head]
		sorted = append(sorted, files[idx].path)
		for _, dep := range edges[idx] {
			inDeg[dep]--
			if inDeg[dep] == 0 {
				queue = append(queue, dep)
			}
		}
	}

	if len(sorted) != n {
		var cycle []string
		for i := 0; i < n; i++ {
			if inDeg[i] > 0 {
				cycle = append(cycle, files[i].path)
			}
		}
		return nil, fmt.Errorf("circular dependency: %v", cycle)
	}

	return sorted, nil
}

func (s *State) DoFileSandboxed(path string) error {
	code := fmt.Sprintf(`_load_file_sandboxed(%q)`, path)
	return s.DoString(code)
}

func (s *State) DoStringSandboxed(code string) error {
	wrapper := fmt.Sprintf(`_load_string_sandboxed(%q)`, code)
	return s.DoString(wrapper)
}

func (s *State) ResetOwner() error {
	return s.DoString(`_current_owner_player = -1; _current_owner_char = -1`)
}

func (s *State) StackSize() int {
	return int(C.lua_gettop(s.L))
}
