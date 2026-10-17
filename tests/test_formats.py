import zipfile

from tests.test_dvds import proposals


def test_files_outside_the_supported_formats_are_listed(folder_of):
    client, folder = folder_of("amiga")
    with zipfile.ZipFile(folder / "A (Europe).zip", "w") as z:
        z.writestr("A (Europe) (Disk 1 of 2).ipf", b"CAPS")
        z.writestr("A (Europe) (Disk 2 of 2).ipf", b"CAPS")
    (folder / "B (Europe).scp").write_bytes(b"SCP")
    with zipfile.ZipFile(folder / "C (Europe).zip", "w") as z:
        z.writestr("C (Europe).scp", b"SCP")
    (folder / "README").write_bytes(b"read me")
    (folder / "notes.txt").write_bytes(b"ignored by name")
    rows = proposals(client, "amiga")
    detail = client.get("/api/folders/amiga").json()
    assert {f["rel_path"]: f["reason"] for f in detail["unsupported"]} == {
        "B (Europe).scp": ".scp is not a supported format",
        "C (Europe).zip": "no supported ROM inside (it holds .scp)",
        "README": "no file extension",
    }
    # A multi-disk game's zip is complete as it is.
    assert rows["A (Europe).zip"]["status"] == "done"
    assert rows["C (Europe).zip"]["note"].startswith("no Amiga ROM inside (ipf, adf")


def test_romsets_are_not_judged_by_their_chip_names(folder_of):
    client, folder = folder_of("neogeomvs")
    with zipfile.ZipFile(folder / "mslug.zip", "w") as z:
        z.writestr("201-p1.p1", b"\0")
        z.writestr("201-c1.c1", b"\0")
    proposals(client, "neogeomvs")
    assert client.get("/api/folders/neogeomvs").json()["unsupported"] == []
