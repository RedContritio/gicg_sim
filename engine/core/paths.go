// core/paths.go
package core

import (
	"fmt"
	"os"
	"path/filepath"
)

// findProjectRoot 从 startDir 向上查找项目根目录
// 项目根目录的判定：包含 data/characters 子目录
func findProjectRoot(startDir string) (string, error) {
	current := startDir
	for {
		// 检查是否存在 data/characters 目录
		charsDir := filepath.Join(current, "data", "characters")
		info, err := os.Stat(charsDir)
		if err == nil && info.IsDir() {
			return current, nil
		}

		parent := filepath.Dir(current)
		if parent == current {
			break
		}
		current = parent
	}
	return "", fmt.Errorf("project root not found from %s", startDir)
}

// getWorkingDir 获取当前工作目录（可测试替换）
var getWorkingDir = os.Getwd

// GetProjectRoot 自动查找项目根目录
func GetProjectRoot() string {
	wd, err := getWorkingDir()
	if err != nil {
		return ""
	}
	root, err := findProjectRoot(wd)
	if err != nil {
		return ""
	}
	return root
}

// GetDataDir 获取数据目录路径
func GetDataDir() string {
	root := GetProjectRoot()
	if root == "" {
		return ""
	}
	return filepath.Join(root, "data")
}
