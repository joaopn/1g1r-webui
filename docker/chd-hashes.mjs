// CRC32, MD5 and SHA1 of each track of a CHD, as chdman would extract it (split .bin
// tracks for CD-ROM, .gdi tracks for GD-ROM, the whole image for DVD and raw CHDs).
// Tracks are streamed through igir's chdman library into the hashes: nothing is written.
// Usage: node chd-hashes.mjs <chdman module> <chunk bytes> <file.chd>; prints JSON.
import crypto from "node:crypto";
import zlib from "node:zlib";

const [modulePath, chunkArg, file] = process.argv.slice(2);
const { default: chdman } = await import(modulePath);
const highWaterMark = Number(chunkArg);

async function hash(readable) {
  const md5 = crypto.createHash("md5");
  const sha1 = crypto.createHash("sha1");
  let crc = 0;
  let size = 0;
  for await (const chunk of readable) {
    md5.update(chunk);
    sha1.update(chunk);
    crc = zlib.crc32(chunk, crc);
    size += chunk.length;
  }
  return {
    size,
    crc32: (crc >>> 0).toString(16).padStart(8, "0"),
    md5: md5.digest("hex"),
    sha1: sha1.digest("hex"),
  };
}

const info = await chdman.info({ inputFilename: file });
const tracks = [];
if (info.type === "CD_ROM" || info.type === "GD_ROM") {
  const gdi = info.type === "GD_ROM";
  const listing = gdi
    ? await chdman.listGdRomTracks({ inputFilename: file, trackBaseName: "track", gdiName: "disc.gdi" })
    : await chdman.listCdBinCueTracks({
        inputFilename: file,
        binNamePattern: "track %t.bin",
        cueName: "disc.cue",
      });
  for (const track of listing.tracks) {
    const readable = chdman.openTrackReader({
      inputFilename: file,
      mode: gdi ? "gdi" : "cuebin",
      trackIndex: track.index,
      highWaterMark,
    });
    tracks.push({ index: track.index, type: track.type, ...(await hash(readable)) });
  }
} else {
  const readable = chdman.openRawReader({ inputFilename: file, highWaterMark });
  tracks.push({ index: 0, type: info.type, ...(await hash(readable)) });
}
process.stdout.write(JSON.stringify({ type: info.type, tracks }));
