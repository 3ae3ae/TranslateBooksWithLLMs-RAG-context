const { readdirSync } = require('node:fs');
const { join } = require('node:path');
const { spawnSync } = require('node:child_process');

// Node treats an explicit directory as an entry point, not a test discovery root.
const files = readdirSync(__dirname).filter(file => file.endsWith('.test.mjs'));
const env = { ...process.env };
// The child must start a new test runner instead of inheriting this test's context.
delete env.NODE_TEST_CONTEXT;
const result = spawnSync(process.execPath, ['--test', ...files.map(file => join(__dirname, file))], {
    stdio: 'inherit',
    env,
});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
