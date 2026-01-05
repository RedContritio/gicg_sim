"""
角色加载器 - 从 YAML 配置文件加载角色
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml  # type: ignore

from ...constants.element import CostElement, DamageElement, Element
from ...constants.id import CharacterID
from ...constants.skill import SkillType
from ..cost import Cost
from ..skill import (
    BaseSkill,
    Skill_ElementalBurst,
    Skill_ElementalSkill,
    Skill_NormalAttack,
    make_standard_cost,
)
from ._base import Character


# 数据目录路径
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "characters"


def _parse_element(element_str: str) -> Element:
    """解析元素字符串为 Element 枚举"""
    try:
        return Element[element_str]
    except KeyError as exc:
        raise ValueError(f"Unknown element: {element_str}") from exc


def _parse_damage_element(element_str: str) -> DamageElement:
    """解析伤害元素字符串为 DamageElement 枚举"""
    try:
        return DamageElement[element_str]
    except KeyError as exc:
        raise ValueError(f"Unknown damage element: {element_str}") from exc


def _parse_cost_element(element_str: Optional[str]) -> Optional[CostElement]:
    """解析费用元素字符串为 CostElement 枚举"""
    if element_str is None:
        return None
    try:
        return CostElement[element_str]
    except KeyError as exc:
        raise ValueError(f"Unknown cost element: {element_str}") from exc


def _parse_skill_type(type_str: str) -> SkillType:
    """解析技能类型字符串"""
    type_map = {
        "normal_attack": SkillType.Normal_Attack,
        "elemental_skill": SkillType.Elemental_Skill,
        "elemental_burst": SkillType.Elemental_Burst,
    }
    if type_str not in type_map:
        raise ValueError(f"Unknown skill type: {type_str}")
    return type_map[type_str]


def _parse_cost(cost_data: Dict[str, Any]) -> Cost:
    """解析费用配置"""
    element = _parse_cost_element(cost_data.get("element"))
    element_count = cost_data.get("element_count", 0)
    matching_count = cost_data.get("matching_count", 0)
    any_count = cost_data.get("any_count", 0)
    energy = cost_data.get("energy")

    return make_standard_cost(
        element,
        element_count,
        matching_count,
        any_count,
        energy
    )


def _parse_skill(skill_data: Dict[str, Any]) -> BaseSkill:
    """解析技能配置"""
    name = skill_data["name"]
    skill_type = _parse_skill_type(skill_data["type"])
    damage_element = _parse_damage_element(skill_data["damage_element"])
    damage_count = skill_data.get("damage_count")
    cost = _parse_cost(skill_data.get("cost", {}))

    # 根据技能类型创建对应的技能类
    if skill_type == SkillType.Normal_Attack:
        return Skill_NormalAttack(name, damage_element, cost, damage_count)
    elif skill_type == SkillType.Elemental_Skill:
        return Skill_ElementalSkill(name, damage_element, cost, damage_count)
    elif skill_type == SkillType.Elemental_Burst:
        return Skill_ElementalBurst(name, damage_element, cost, damage_count)
    else:
        return BaseSkill(name, damage_element, cost, skill_type, damage_count)


class ConfiguredCharacter(Character):
    """从配置文件加载的角色类"""

    def __init__(self,
                 name: str,
                 max_hp: int,
                 max_energy: int,
                 element: Element,
                 skills: List[BaseSkill],
                 char_id: CharacterID) -> None:
        super().__init__(name, max_hp, max_energy, element, char_id)
        self._set_skills(skills)


def load_character_from_yaml(yaml_path: str | Path,
                             char_id: CharacterID) -> Character:
    """从 YAML 文件加载角色

    Args:
        yaml_path: YAML 文件路径
        char_id: 角色 ID

    Returns:
        Character: 加载的角色实例
    """
    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    name = data["name"]
    element = _parse_element(data["element"])
    max_hp = data["max_hp"]
    max_energy = data["max_energy"]

    skills = [_parse_skill(skill_data) for skill_data in data.get("skills", [])]

    return ConfiguredCharacter(
        name=name,
        max_hp=max_hp,
        max_energy=max_energy,
        element=element,
        skills=skills,
        char_id=char_id
    )


def load_character_by_name(name: str, char_id: CharacterID) -> Character:
    """通过角色名称加载角色

    Args:
        name: 角色名称（对应 YAML 文件名，不含扩展名）
        char_id: 角色 ID

    Returns:
        Character: 加载的角色实例
    """
    yaml_path = DATA_DIR / f"{name}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"Character config not found: {yaml_path}")
    return load_character_from_yaml(yaml_path, char_id)


def list_available_characters() -> List[str]:
    """列出所有可用的角色配置

    Returns:
        List[str]: 角色名称列表
    """
    if not DATA_DIR.exists():
        return []
    return [f.stem for f in DATA_DIR.glob("*.yaml")]

