const crypto = require('crypto');

// Function to generate a random UUID
function randomUUID() {
  return crypto.randomUUID();
}

// Export the function so it can be used in other files
module.exports = {
  randomUUID
};