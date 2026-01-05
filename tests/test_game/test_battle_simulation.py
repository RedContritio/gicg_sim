"""
测试场景：简化的对战模拟

场景描述：
- 开始游戏，双方各自只有一名角色（TestPyro，火元素），30张无效牌
- 开局后，各抽五张无效牌，不更换
- 每个回合：
  - 双方各获得8个和角色不同色的骰子（非火元素），不更换
  - 先手方：烧一张牌（元素调和）获得一个火骰子，使用普通攻击造成2点物理伤害
  - 后手方：直接结束回合
- 重复直到后手方角色被击败（HP <= 0），游戏结束
"""

from typing import List

from gicg_sim import Game
from gicg_sim.constants.element import DiceElement
from gicg_sim.constants.id import CharacterID
from gicg_sim.game.card import DummyCard
from gicg_sim.game.character import TestPyro, load_character_by_name
from gicg_sim.game.dice import DiceState


def create_dummy_deck(count: int = 30) -> List[DummyCard]:
    """创建指定数量的无效牌牌组"""
    return [DummyCard() for _ in range(count)]


def create_non_matching_dice(exclude_element: DiceElement, total: int = 8) -> DiceState:
    """创建不包含指定元素的骰子状态
    
    平均分配到其他元素（不包括万能骰）
    """
    dice_state = DiceState()
    
    # 获取除排除元素和万能骰外的其他元素
    other_elements = [
        e for e in DiceElement 
        if e != exclude_element and e != DiceElement.Omni
    ]
    
    # 平均分配骰子
    per_element = total // len(other_elements)
    remainder = total % len(other_elements)
    
    for i, element in enumerate(other_elements):
        count = per_element + (1 if i < remainder else 0)
        dice_state[element] = count
    
    return dice_state


def setup_game() -> Game:
    """初始化游戏状态（使用硬编码角色类）"""
    game = Game()
    
    # 双方各自设置一名 TestPyro 角色
    for side_idx, side in enumerate(game.sides):
        character = TestPyro(CharacterID(side_idx))
        side._add_character(character)
        
        # 设置30张无效牌
        side.cards_tile = create_dummy_deck(30)
    
    return game


def setup_game_from_yaml(character_name: str = "test_pyro") -> Game:
    """初始化游戏状态（使用 YAML 配置加载角色）
    
    Args:
        character_name: 角色配置文件名（不含扩展名）
    """
    game = Game()
    
    # 双方各自从 YAML 加载角色
    for side_idx, side in enumerate(game.sides):
        character = load_character_by_name(character_name, CharacterID(side_idx))
        side._add_character(character)
        
        # 设置30张无效牌
        side.cards_tile = create_dummy_deck(30)
    
    return game


def phase_opening(game: Game):
    """开局阶段：双方各抽5张牌"""
    for side in game.sides:
        side.draw_cards(5)
    
    print("=== 开局阶段 ===")
    for i, side in enumerate(game.sides):
        print(f"玩家{i}: 手牌 {len(side.cards_hand)} 张, "
              f"牌堆 {len(side.cards_tile)} 张")


def phase_roll_dice(game: Game):
    """投掷阶段：双方各获得8个非火元素骰子"""
    for side in game.sides:
        # 清空旧骰子
        side.dices.clear()
        # 分配非火元素骰子
        non_fire_dice = create_non_matching_dice(DiceElement.Pyro, 8)
        side._set_dice(non_fire_dice)


def action_first_player(game: Game) -> bool:
    """先手方行动：元素调和 + 普通攻击
    
    Returns:
        bool: 是否成功执行行动
    """
    first_side = game.sides[0]
    second_side = game.sides[1]
    
    # 元素调和：弃一张牌获得一个火骰子
    if not first_side.cards_hand:
        print("先手方没有手牌，无法元素调和")
        return False
    
    # 执行元素调和
    first_side.elemental_tuning()
    
    # 使用普通攻击
    character = first_side.active_character
    skill = character.normal_attack
    
    # 检查骰子是否足够
    # 普通攻击需要: 1火 + 2任意
    fire_dice = first_side.dices[DiceElement.Pyro]
    total_dice = first_side.dices.total()
    
    if fire_dice < 1 or total_dice < 3:
        print(f"骰子不足: 火={fire_dice}, 总计={total_dice}")
        return False
    
    # 消耗骰子: 1火 + 2任意
    first_side.dices.remove(DiceElement.Pyro, 1)
    
    # 从其他元素中消耗2个任意骰子
    remaining_to_consume = 2
    for element in DiceElement:
        if remaining_to_consume <= 0:
            break
        available = first_side.dices[element]
        consume = min(available, remaining_to_consume)
        first_side.dices.remove(element, consume)
        remaining_to_consume -= consume
    
    # 造成伤害
    damage = skill.damage_count if skill.damage_count else 0
    target_character = second_side.active_character
    actual_damage = target_character.take_damage(damage)
    
    print(f"先手方 {character.name} 使用普通攻击，"
          f"对 {target_character.name} 造成 {actual_damage} 点伤害，"
          f"目标剩余 HP: {target_character.current_hp}")
    
    return True


def action_second_player(game: Game):
    """后手方行动：直接结束回合"""
    second_side = game.sides[1]
    second_side.end_round()
    print("后手方宣布结束回合")


def check_game_over(game: Game) -> bool:
    """检查游戏是否结束
    
    Returns:
        bool: True 表示游戏结束
    """
    for i, side in enumerate(game.sides):
        if side.is_all_defeated():
            print(f"=== 游戏结束 ===")
            print(f"玩家{i} 所有角色被击败!")
            return True
    return False


def run_battle_simulation():
    """运行完整的对战模拟"""
    print("========== 对战模拟开始 ==========\n")
    
    # 1. 初始化游戏
    game = setup_game()
    
    # 2. 开局阶段
    phase_opening(game)
    print()
    
    round_number = 0
    max_rounds = 20  # 安全限制，防止无限循环
    
    while round_number < max_rounds:
        round_number += 1
        print(f"=== 第 {round_number} 回合 ===")
        
        # 3. 投掷阶段
        phase_roll_dice(game)
        print(f"双方各获得 8 个非火元素骰子")
        
        # 4. 行动阶段
        # 先手方行动
        print("\n--- 先手方行动 ---")
        if not action_first_player(game):
            print("先手方无法行动，游戏异常结束")
            break
        
        # 检查游戏是否结束
        if check_game_over(game):
            break
        
        # 后手方行动
        print("\n--- 后手方行动 ---")
        action_second_player(game)
        
        # 5. 回合结束
        for side in game.sides:
            side.reset_round_state()
        
        print()
    
    print("\n========== 对战模拟结束 ==========")
    return game


# ===== 测试用例 =====

def test_setup_game():
    """测试游戏初始化"""
    game = setup_game()
    
    # 验证双方都有一名角色
    assert len(game.sides[0].characters) == 1
    assert len(game.sides[1].characters) == 1
    
    # 验证角色是 TestPyro
    assert game.sides[0].active_character.name == "TestPyro"
    assert game.sides[1].active_character.name == "TestPyro"
    
    # 验证牌堆
    assert len(game.sides[0].cards_tile) == 30
    assert len(game.sides[1].cards_tile) == 30


def test_create_non_matching_dice():
    """测试创建非匹配骰子"""
    dice = create_non_matching_dice(DiceElement.Pyro, 8)
    
    # 不应有火元素骰子
    assert dice[DiceElement.Pyro] == 0
    # 不应有万能骰
    assert dice[DiceElement.Omni] == 0
    # 总数应为8
    assert dice.total() == 8


def test_opening_phase():
    """测试开局阶段"""
    game = setup_game()
    phase_opening(game)
    
    # 验证双方都抽了5张牌
    assert len(game.sides[0].cards_hand) == 5
    assert len(game.sides[1].cards_hand) == 5
    # 验证牌堆减少
    assert len(game.sides[0].cards_tile) == 25
    assert len(game.sides[1].cards_tile) == 25


def test_elemental_tuning():
    """测试元素调和"""
    game = setup_game()
    phase_opening(game)
    phase_roll_dice(game)
    
    first_side = game.sides[0]
    initial_hand_count = len(first_side.cards_hand)
    initial_fire_dice = first_side.dices[DiceElement.Pyro]
    
    # 执行元素调和
    result = first_side.elemental_tuning()
    
    assert result is True
    # 手牌减少1张
    assert len(first_side.cards_hand) == initial_hand_count - 1
    # 火元素骰子增加1个
    assert first_side.dices[DiceElement.Pyro] == initial_fire_dice + 1


def test_full_battle_simulation():
    """测试完整对战模拟
    
    验证：
    - 先手方通过普通攻击（2伤害）击败后手方角色（10HP）
    - 预期需要5个回合 (5 * 2 = 10 伤害)
    """
    game = run_battle_simulation()
    
    # 后手方角色应该被击败
    second_player_character = game.sides[1].active_character
    assert second_player_character.is_defeated()
    assert second_player_character.current_hp == 0
    
    # 先手方角色应该存活
    first_player_character = game.sides[0].active_character
    assert not first_player_character.is_defeated()
    assert first_player_character.current_hp == 10  # 未受伤害


def test_battle_rounds_count():
    """测试对战回合数
    
    后手方 HP=10, 每回合受到 2 点伤害
    需要 ceil(10/2) = 5 回合
    """
    game = setup_game()
    phase_opening(game)
    
    round_count = 0
    while not game.sides[1].is_all_defeated() and round_count < 20:
        round_count += 1
        phase_roll_dice(game)
        action_first_player(game)
    
    # 应该正好5回合结束战斗
    assert round_count == 5
    assert game.sides[1].active_character.current_hp == 0


def test_setup_game_from_yaml():
    """测试使用 YAML 配置初始化游戏"""
    game = setup_game_from_yaml("test_pyro")
    
    # 验证双方都有一名角色
    assert len(game.sides[0].characters) == 1
    assert len(game.sides[1].characters) == 1
    
    # 验证角色是 TestPyro（从 YAML 加载）
    assert game.sides[0].active_character.name == "TestPyro"
    assert game.sides[1].active_character.name == "TestPyro"
    
    # 验证角色属性
    char = game.sides[0].active_character
    assert char.max_hp == 10
    assert char.current_hp == 10


def test_battle_with_yaml_characters():
    """测试使用 YAML 配置角色的对战
    
    与 test_battle_rounds_count 相同的逻辑，但使用 YAML 加载的角色
    """
    game = setup_game_from_yaml("test_pyro")
    
    # 开局阶段
    for side in game.sides:
        side.draw_cards(5)
    
    round_count = 0
    while not game.sides[1].is_all_defeated() and round_count < 20:
        round_count += 1
        phase_roll_dice(game)
        action_first_player(game)
    
    # 应该正好5回合结束战斗
    assert round_count == 5
    assert game.sides[1].active_character.current_hp == 0


if __name__ == "__main__":
    # 直接运行时执行模拟
    run_battle_simulation()

