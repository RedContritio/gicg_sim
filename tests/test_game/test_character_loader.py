"""
测试角色 YAML 加载器
"""

from gicg_sim.constants.element import DamageElement, Element
from gicg_sim.constants.id import CharacterID
from gicg_sim.constants.skill import SkillType
from gicg_sim.game.character import (
    list_available_characters,
    load_character_by_name,
)


def test_list_available_characters():
    """测试列出可用角色"""
    characters = list_available_characters()
    
    assert "test_pyro" in characters
    assert "khaenriahn" in characters


def test_load_test_pyro():
    """测试加载 TestPyro 角色"""
    character = load_character_by_name("test_pyro", CharacterID(1))
    
    assert character.name == "TestPyro"
    assert character.element == Element.Pyro
    assert character.max_hp == 10
    assert character.max_energy == 2
    assert character.current_hp == 10
    
    # 验证技能
    assert len(character.skills) == 1
    skill = character.skills[0]
    assert skill.name == "普通攻击"
    assert skill.skill_type == SkillType.Normal_Attack
    assert skill.element == DamageElement.Physical
    assert skill.damage_count == 2


def test_load_khaenriahn():
    """测试加载 Khaenriahn 角色"""
    character = load_character_by_name("khaenriahn", CharacterID(2))
    
    assert character.name == "Khaenriahn"
    assert character.element == Element.Undefined
    assert character.max_hp == 10
    assert character.max_energy == 2
    
    # 验证技能
    assert len(character.skills) == 1
    skill = character.skills[0]
    assert skill.name == "普通攻击"
    assert skill.skill_type == SkillType.Normal_Attack
    assert skill.element == DamageElement.Physical


def test_character_take_damage():
    """测试从 YAML 加载的角色受到伤害"""
    character = load_character_by_name("test_pyro", CharacterID(1))
    
    assert character.current_hp == 10
    
    # 受到 3 点伤害
    actual = character.take_damage(3)
    assert actual == 3
    assert character.current_hp == 7
    assert not character.is_defeated()
    
    # 受到 10 点伤害（超出剩余 HP）
    actual = character.take_damage(10)
    assert actual == 7  # 只能造成 7 点实际伤害
    assert character.current_hp == 0
    assert character.is_defeated()


def test_multiple_characters_different_ids():
    """测试加载多个角色使用不同 ID"""
    char1 = load_character_by_name("test_pyro", CharacterID(1))
    char2 = load_character_by_name("test_pyro", CharacterID(2))
    
    assert char1.id != char2.id
    assert char1.id == CharacterID(1)
    assert char2.id == CharacterID(2)
    
    # 验证它们是独立的实例
    char1.take_damage(5)
    assert char1.current_hp == 5
    assert char2.current_hp == 10  # char2 不受影响

