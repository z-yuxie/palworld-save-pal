import type { ItemContainer, ItemContainerSlot, PresetProfile } from '$lib/types';
import { deepCopy } from './deep-copy';

const ZERO_UUID = '00000000-0000-0000-0000-000000000000';

/** 深拷贝槽位数组（每个槽位独立，含 dynamic_item）。 */
function cloneSlots(slots: readonly ItemContainerSlot[]): ItemContainerSlot[] {
	return slots.map((slot) => {
		const result: ItemContainerSlot = { ...slot };
		if (slot.dynamic_item) {
			result.dynamic_item = deepCopy(slot.dynamic_item);
		}
		return result;
	});
}

/**
 * 按选中顺序扁平化预设的 storage_container.slots，
 * 自动过滤 static_id === 'None' 的空槽。
 * 跳过没有 storage_container 的预设。
 * 返回的每个槽位都是深拷贝，修改不会污染预设模板。
 */
export function flattenStoragePresetSlots(
	presets: readonly PresetProfile[]
): readonly ItemContainerSlot[] {
	const slots: ItemContainerSlot[] = [];
	for (const preset of presets) {
		const sc = preset.storage_container;
		if (!sc) continue;
		for (const ps of sc.slots ?? []) {
			if (ps.static_id !== 'None') {
				const cloned: ItemContainerSlot = { ...ps };
				if (ps.dynamic_item) {
					cloned.dynamic_item = deepCopy(ps.dynamic_item);
				}
				slots.push(cloned);
			}
		}
	}
	return slots;
}

/**
 * 检查预设是否与目标容器兼容。
 * - 非 storage 类型或缺少 storage_container → false
 * - 同 key → true
 * - preset key 或 container key 为 '*' → true
 * - 跨 key：仅当预设中非空物品数 ≤ 容器槽数时返回 true
 */
export function isStoragePresetCompatible(
	container: Pick<ItemContainer, 'key' | 'slots'>,
	preset: PresetProfile
): boolean {
	if (preset.type !== 'storage') return false;
	const sc = preset.storage_container;
	if (!sc) return false;

	const containerKey = container.key;
	const presetKey = sc.key;

	if (containerKey === presetKey || containerKey === '*' || presetKey === '*') return true;

	// 跨 key：统计预设中非空物品数
	const presetSlots = sc.slots ?? [];
	const nonEmptyCount = presetSlots.filter((s) => s.static_id !== 'None').length;
	return nonEmptyCount <= container.slots.length;
}

/**
 * Apply 模式：用预设物品按顺序覆盖目标容器，溢出截断，余槽清空。
 * - 保留目标槽位的 slot_index 和元数据
 * - 动态物品 deepCopy 且 local_id 归零
 * - 不修改 target 和 presets 输入
 * - 返回新数组（即使 presets 为空也返回独立副本）
 */
export function applyStoragePresets(
	target: readonly ItemContainerSlot[],
	presets: readonly PresetProfile[]
): ItemContainerSlot[] {
	const flatSlots = flattenStoragePresetSlots(presets);
	if (flatSlots.length === 0) return cloneSlots(target);

	return target.map((slot, idx) => {
		if (idx < flatSlots.length) {
			const presetSlot = flatSlots[idx];
			let dynamic_item = undefined;
			if (presetSlot.dynamic_item) {
				dynamic_item = deepCopy(presetSlot.dynamic_item);
				dynamic_item.local_id = ZERO_UUID;
			}
			return {
				...slot,
				static_id: presetSlot.static_id,
				count: presetSlot.count,
				dynamic_item
			};
		}
		return { ...slot, static_id: 'None', count: 0, dynamic_item: undefined };
	});
}

/**
 * Append 模式：将预设物品按顺序填入目标容器中原本为空的槽位（static_id === 'None'）。
 * - 已有物品的槽位完全保留（深拷贝，包括 dynamic_item，与 target 独立）
 * - 溢出截断
 * - 动态物品 deepCopy 且 local_id 归零
 * - 不修改 target 和 presets 输入
 * - 返回新数组（即使 presets 为空也返回独立副本）
 */
export function appendStoragePresets(
	target: readonly ItemContainerSlot[],
	presets: readonly PresetProfile[]
): ItemContainerSlot[] {
	const flatSlots = flattenStoragePresetSlots(presets);

	const emptyIndices: number[] = [];
	for (let i = 0; i < target.length; i++) {
		if (target[i].static_id === 'None') {
			emptyIndices.push(i);
		}
	}

	const result = cloneSlots(target);
	if (flatSlots.length === 0) return result;

	let flatIdx = 0;
	for (const emptyIdx of emptyIndices) {
		if (flatIdx >= flatSlots.length) break;
		const presetSlot = flatSlots[flatIdx];

		result[emptyIdx].static_id = presetSlot.static_id;
		result[emptyIdx].count = presetSlot.count;
		if (presetSlot.dynamic_item) {
			result[emptyIdx].dynamic_item = deepCopy(presetSlot.dynamic_item);
			result[emptyIdx].dynamic_item!.local_id = ZERO_UUID;
		} else {
			result[emptyIdx].dynamic_item = undefined;
		}

		flatIdx++;
	}

	return result;
}
