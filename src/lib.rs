#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PeerNode {
    pub hostname: String,
    pub ip_address: String,
    pub port: u16,
}

#[derive(Debug, Default)]
pub struct LanFileshareDaemon {
    peers: Vec<PeerNode>,
}

impl LanFileshareDaemon {
    pub fn new() -> Self { Self { peers: Vec::new() } }
    pub fn add_peer(&mut self, host: &str, ip: &str, port: u16) {
        self.peers.push(PeerNode {
            hostname: host.into(),
            ip_address: ip.into(),
            port,
        });
    }
    pub fn peer_count(&self) -> usize { self.peers.len() }
    pub fn find_peer(&self, host: &str) -> Option<&PeerNode> {
        self.peers.iter().find(|p| p.hostname == host)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_lan_fileshare_daemon_aaa() {
        // Arrange
        let mut daemon = LanFileshareDaemon::new();
        // Act
        daemon.add_peer("desktop-alpha", "192.168.1.10", 42000);
        daemon.add_peer("laptop-beta", "192.168.1.25", 42000);
        // Assert
        assert_eq!(daemon.peer_count(), 2);
        let p = daemon.find_peer("laptop-beta").expect("Peer must exist");
        assert_eq!(p.ip_address, "192.168.1.25");
    }
}
