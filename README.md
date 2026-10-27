    # SigmaOS-LAN-fileshare

    Warpinator-style LAN send/receive

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/linuxmint/warpinator
- https://github.com/t4t5/owly

    ## Design principles applied
    - **Plan Before Act**
- **Defensive Programming**
- **Fail-Fast**
- **Least Privilege**
- **KISS**
- **Deterministic Testing**

    ## Usage
    Verbs: `send-plan, receive-plan, peers, verify`

    ```
    $ sigma-lanshare peers peers.conf
alpha   192.168.1.10:8443  key=...
beta    192.168.1.11:8443
$ sigma-lanshare send-plan peers.conf alpha ./trip --files img1.jpg img2.jpg
$ sigma-lanshare receive-plan manifest.json --out ~/Downloads/lanshare
$ sigma-lanshare verify manifest.json ~/Downloads/lanshare
ok=2 missing=0 mismatched=0

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
