// Story notes and style guides are stored as files; show them without extensions.
export const displayName = (filename) => String(filename || '').replace(/\.(txt|ya?ml)$/i, '');
export const noteFilename = (name) => (/\.txt$/i.test(name) ? name : `${name}.txt`);
