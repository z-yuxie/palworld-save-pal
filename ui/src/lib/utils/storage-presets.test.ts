import { describe, expect, it } from 'vitest';
import type { DynamicItem, ItemContainerSlot, PresetProfile } from '$lib/types';
import {
	appendStoragePresets,
	applyStoragePresets,
	flattenStoragePresetSlots,
	isStoragePresetCompatible
} from './storage-presets';

// ── helpers ──────────────────────────────────────────────────────────

function s(index: number, static_id: string, count = 1, dynamic_item?: DynamicItem): ItemContainerSlot {
	return { slot_index: index, static_id, count, dynamic_item };
}
function none(index: number): ItemContainerSlot {
	return { slot_index: index, static_id: 'None', count: 0 };
}
function makePreset(name: string, key: string, type: string = 'storage', slots: ItemContainerSlot[] = []): PresetProfile {
	return {
		name,
		type: type as PresetProfile['type'],
		storage_container: type === 'storage' ? { key, slots } : undefined
	};
}
const dyn: DynamicItem = {
	local_id: 'original-uuid-1234',
	durability: 100,
	type: 'weapon',
	gender: '',
	talent_hp: 0,
	talent_shot: 0,
	talent_defense: 0,
	learned_skills: [],
	active_skills: [],
	passive_skills: [],
	modified: false
};

// ── TEST 1: flattenStoragePresetSlots order + None filter ────────────

describe('flattenStoragePresetSlots', () => {
	it('preserves selection order and filters static_id=None', () => {
		const presets: PresetProfile[] = [
			makePreset('First', 'container-1', 'storage', [
				none(0),
				s(1, 'Wood'),
				s(2, 'Stone')
			]),
			makePreset('Second', 'container-1', 'storage', [
				s(0, 'Iron', 5),
				none(1),
				s(2, 'Coal')
			])
		];

		const result = flattenStoragePresetSlots(presets);

		expect(result).toHaveLength(4);
		expect(result.map((r) => r.static_id)).toEqual(['Wood', 'Stone', 'Iron', 'Coal']);
		expect(result[2].count).toBe(5);
	});

	it('returns empty array for empty input', () => {
		expect(flattenStoragePresetSlots([])).toEqual([]);
	});

	it('skips preset without storage_container', () => {
		const presets: PresetProfile[] = [
			makePreset('NoStorage', '', 'inventory', []),
			makePreset('Has', 'box', 'storage', [s(0, 'Gold')])
		];

		const result = flattenStoragePresetSlots(presets);
		expect(result).toHaveLength(1);
		expect(result[0].static_id).toBe('Gold');
	});
});

// ── TEST 2-3: isStoragePresetCompatible ──────────────────────────────

describe('isStoragePresetCompatible', () => {
	const container = { key: 'box-1', slots: Array.from({ length: 10 }, (_, i) => none(i)) };

	it('returns false for non-storage preset', () => {
		const preset = makePreset('Inv', '', 'inventory');
		expect(isStoragePresetCompatible(container, preset)).toBe(false);
	});

	it('returns false when storage_container is missing', () => {
		const preset: PresetProfile = { name: 'NoContainer', type: 'storage' };
		expect(isStoragePresetCompatible(container, preset)).toBe(false);
	});

	// ── TEST 4: same key ─────────────────────────────────────────────

	it('returns true when keys match', () => {
		const preset = makePreset('Match', 'box-1', 'storage', [s(0, 'Axe')]);
		expect(isStoragePresetCompatible(container, preset)).toBe(true);
	});

	// ── TEST 5: wildcard keys ────────────────────────────────────────

	it('returns true when preset key is "*"', () => {
		const preset = makePreset('WildPreset', '*', 'storage', [s(0, 'Pickaxe')]);
		expect(isStoragePresetCompatible(container, preset)).toBe(true);
	});

	it('returns true when container key is "*"', () => {
		const starContainer = { key: '*', slots: Array.from({ length: 5 }, (_, i) => none(i)) };
		const preset = makePreset('WildContainer', 'box-2', 'storage', [s(0, 'Sword')]);
		expect(isStoragePresetCompatible(starContainer, preset)).toBe(true);
	});

	// ── TEST 6: cross-key capacity ───────────────────────────────────

	it('cross-key: true when non-empty preset items ≤ target slots', () => {
		const smallContainer = { key: 'box-3', slots: Array.from({ length: 3 }, (_, i) => none(i)) };
		const preset = makePreset('Cross', 'box-4', 'storage', [
			s(0, 'A'), none(1), s(2, 'B') // 2 non-empty
		]);
		expect(isStoragePresetCompatible(smallContainer, preset)).toBe(true);
	});

	it('cross-key: false when non-empty preset items > target slots', () => {
		const tinyContainer = { key: 'box-5', slots: [none(0)] };
		const preset = makePreset('TooBig', 'box-6', 'storage', [
			s(0, 'A'), s(1, 'B') // 2 non-empty, only 1 slot
		]);
		expect(isStoragePresetCompatible(tinyContainer, preset)).toBe(false);
	});
});

// ── TEST 7-8: applyStoragePresets ────────────────────────────────────

describe('applyStoragePresets', () => {
	it('overwrites slots in order, preserves slot_index, clears remainder', () => {
		const target: ItemContainerSlot[] = [
			s(0, 'OldA', 99),
			s(1, 'OldB', 99),
			s(2, 'OldC', 99)
		];

		const presets: PresetProfile[] = [
			makePreset('P1', 'box', 'storage', [s(0, 'NewA', 10), s(1, 'NewB', 20)])
		];

		const result = applyStoragePresets(target, presets);

		expect(result).toHaveLength(3);
		// slot_index preserved
		expect(result[0].slot_index).toBe(0);
		expect(result[1].slot_index).toBe(1);
		expect(result[2].slot_index).toBe(2);
		// overwritten
		expect(result[0].static_id).toBe('NewA');
		expect(result[0].count).toBe(10);
		expect(result[1].static_id).toBe('NewB');
		expect(result[1].count).toBe(20);
		// cleared
		expect(result[2].static_id).toBe('None');
		expect(result[2].count).toBe(0);
		expect(result[2].dynamic_item).toBeUndefined();
	});

	it('truncates overflow when preset items exceed target slots', () => {
		const target: ItemContainerSlot[] = [s(0, 'Old')];
		const presets: PresetProfile[] = [
			makePreset('Overflow', 'box', 'storage', [s(0, 'A'), s(1, 'B'), s(2, 'C')])
		];

		const result = applyStoragePresets(target, presets);

		expect(result).toHaveLength(1);
		expect(result[0].static_id).toBe('A');
	});

	it('multi-preset merge respects selection order', () => {
		const target: ItemContainerSlot[] = [s(0, 'Old'), s(1, 'Old'), s(2, 'Old')];

		const presets: PresetProfile[] = [
			makePreset('First', 'box', 'storage', [s(0, 'Alpha')]),
			makePreset('Second', 'box', 'storage', [s(0, 'Beta'), s(1, 'Gamma')])
		];

		const result = applyStoragePresets(target, presets);
		expect(result.map((r) => r.static_id)).toEqual(['Alpha', 'Beta', 'Gamma']);
	});
});

// ── TEST 9: appendStoragePresets ─────────────────────────────────────

describe('appendStoragePresets', () => {
	it('fills only empty slots, preserves existing non-empty slots, truncates overflow', () => {
		const target: ItemContainerSlot[] = [
			s(0, 'Occupied', 50),
			none(1),
			none(2)
		];

		const presets: PresetProfile[] = [
			makePreset('Append', 'box', 'storage', [s(0, 'Item1'), s(1, 'Item2'), s(2, 'Item3')])
		];

		const result = appendStoragePresets(target, presets);

		expect(result).toHaveLength(3);
		expect(result[0].static_id).toBe('Occupied');
		expect(result[0].count).toBe(50);
		expect(result[1].static_id).toBe('Item1');
		expect(result[2].static_id).toBe('Item2');
		// Item3 overflowed — 只有2个空槽
	});
});

// ── TEST 10: immutability + deepCopy with zeroed UUID ────────────────

describe('immutability and dynamic item cloning', () => {
	it('applyStoragePresets deep-copies dynamic_item with zeroed local_id', () => {
		const target: ItemContainerSlot[] = [s(0, 'Old')];
		const presets: PresetProfile[] = [
			makePreset('Dyn', 'box', 'storage', [s(0, 'Weapon', 1, { ...dyn })])
		];

		const result = applyStoragePresets(target, presets);

		expect(result[0].dynamic_item).toBeDefined();
		expect(result[0].dynamic_item!.local_id).toBe('00000000-0000-0000-0000-000000000000');
		expect(result[0].dynamic_item!.durability).toBe(100);
		// 原模板不变
		expect(presets[0].storage_container!.slots[0].dynamic_item!.local_id).toBe('original-uuid-1234');
	});

	it('appendStoragePresets deep-copies dynamic_item with zeroed local_id', () => {
		const target: ItemContainerSlot[] = [none(0)];
		const presets: PresetProfile[] = [
			makePreset('DynAppend', 'box', 'storage', [s(0, 'Weapon', 1, { ...dyn })])
		];

		const result = appendStoragePresets(target, presets);

		expect(result[0].dynamic_item).toBeDefined();
		expect(result[0].dynamic_item!.local_id).toBe('00000000-0000-0000-0000-000000000000');
		expect(presets[0].storage_container!.slots[0].dynamic_item!.local_id).toBe('original-uuid-1234');
	});

	it('applyStoragePresets does not mutate target input', () => {
		const target: ItemContainerSlot[] = [s(0, 'A', 10), none(1)];
		const snapshot = JSON.stringify(target);

		const presets: PresetProfile[] = [
			makePreset('P', 'box', 'storage', [s(0, 'B')])
		];

		applyStoragePresets(target, presets);

		expect(JSON.stringify(target)).toBe(snapshot);
	});

	it('appendStoragePresets does not mutate target input', () => {
		const target: ItemContainerSlot[] = [s(0, 'A', 10), none(1)];
		const snapshot = JSON.stringify(target);

		const presets: PresetProfile[] = [
			makePreset('P', 'box', 'storage', [s(0, 'B')])
		];

		appendStoragePresets(target, presets);

		expect(JSON.stringify(target)).toBe(snapshot);
	});

	it('applyStoragePresets does not mutate preset input', () => {
		const target: ItemContainerSlot[] = [s(0, 'A')];
		const presets: PresetProfile[] = [
			makePreset('P', 'box', 'storage', [s(0, 'B', 1, { ...dyn })])
		];
		const snapshot = JSON.stringify(presets);

		applyStoragePresets(target, presets);

		expect(JSON.stringify(presets)).toBe(snapshot);
	});

	it('appendStoragePresets does not mutate preset input', () => {
		const target: ItemContainerSlot[] = [none(0)];
		const presets: PresetProfile[] = [
			makePreset('P', 'box', 'storage', [s(0, 'B', 1, { ...dyn })])
		];
		const snapshot = JSON.stringify(presets);

		appendStoragePresets(target, presets);

		expect(JSON.stringify(presets)).toBe(snapshot);
	});
});
