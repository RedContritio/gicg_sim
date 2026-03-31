// core/deck.go
package core

import (
	"math/rand"
	"time"
)

// Deck 牌堆管理器
type Deck struct {
	DrawPile    []string  // 抽牌堆
	DiscardPile []string  // 弃牌堆
	Side        *Side
}

// NewDeck 创建牌堆
func NewDeck(side *Side) *Deck {
	return &Deck{
		DrawPile:    make([]string, 0),
		DiscardPile: make([]string, 0),
		Side:        side,
	}
}

// InitializeWithCard 使用指定卡牌初始化牌堆
func (d *Deck) InitializeWithCard(cardID string, count int) {
	d.DrawPile = make([]string, 0, count)
	for i := 0; i < count; i++ {
		d.DrawPile = append(d.DrawPile, cardID)
	}
	// 洗牌
	d.Shuffle()
}

// Shuffle 洗牌
func (d *Deck) Shuffle() {
	rand.Seed(time.Now().UnixNano())
	rand.Shuffle(len(d.DrawPile), func(i, j int) {
		d.DrawPile[i], d.DrawPile[j] = d.DrawPile[j], d.DrawPile[i]
	})
}

// Draw 抽取指定数量的牌
func (d *Deck) Draw(count int) []string {
	drawn := make([]string, 0, count)
	
	for i := 0; i < count; i++ {
		// 抽牌堆为空时，将弃牌堆洗入
		if len(d.DrawPile) == 0 {
			if len(d.DiscardPile) == 0 {
				break // 没有牌可抽了
			}
			// 弃牌堆洗入抽牌堆
			d.DrawPile = d.DiscardPile
			d.DiscardPile = make([]string, 0)
			d.Shuffle()
		}
		
		// 抽牌
		if len(d.DrawPile) > 0 {
			card := d.DrawPile[0]
			d.DrawPile = d.DrawPile[1:]
			drawn = append(drawn, card)
		}
	}
	
	return drawn
}

// DrawToHand 抽牌到手牌
func (d *Deck) DrawToHand(count int) int {
	cards := d.Draw(count)
	drawn := 0
	for _, card := range cards {
		if d.Side.AddCard(card) {
			drawn++
		} else {
			// 手牌满了，弃置
			d.Discard(card)
		}
	}
	return drawn
}

// Discard 弃置卡牌
func (d *Deck) Discard(cardID string) {
	d.DiscardPile = append(d.DiscardPile, cardID)
}

// DiscardFromHand 从手牌弃置
func (d *Deck) DiscardFromHand(handIndex int) string {
	cardID := d.Side.RemoveCard(handIndex)
	if cardID != "" {
		d.Discard(cardID)
	}
	return cardID
}

// GetDrawPileCount 获取抽牌堆数量
func (d *Deck) GetDrawPileCount() int {
	return len(d.DrawPile)
}

// GetDiscardPileCount 获取弃牌堆数量
func (d *Deck) GetDiscardPileCount() int {
	return len(d.DiscardPile)
}

// GetTotalCount 获取总牌数
func (d *Deck) GetTotalCount() int {
	return len(d.DrawPile) + len(d.DiscardPile) + d.Side.GetHandSize()
}
