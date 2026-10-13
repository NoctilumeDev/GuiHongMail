package dev.guihong.platform;

/** Standard object storage port; no provider-specific API or business ownership model. */
public interface ObjectStore extends AutoCloseable {
    void put(String key, byte[] data);
    byte[] get(String key);
    void delete(String key);
    boolean ready();
    void close();
}
