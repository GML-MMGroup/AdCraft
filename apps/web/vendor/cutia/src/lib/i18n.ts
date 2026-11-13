type TranslateFn = (
	key: string,
	options?: Record<string, unknown>,
) => string;

let _t: TranslateFn = (key) => key;

export function _setGlobalTranslation({
	t,
}: {
	t: TranslateFn;
}) {
	_t = t;
}

export const i18next = {
	t(key: string, options?: Record<string, unknown>): string {
		return _t(key, options);
	},
};
