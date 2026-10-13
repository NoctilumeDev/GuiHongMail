package dev.guihong.platform;

import java.io.IOException;
import java.nio.file.Path;
import java.util.Properties;

public record FoundationSettings(String role, String sourceSha, Path witnessRoot, String internalToken,
                                 String s3Endpoint, String s3Bucket, String s3Key, String s3Secret, String namesrv, String broker) {
    public static FoundationSettings fromEnvironment() throws IOException {
        String role = System.getProperty("guihong.role");
        if (role == null || !role.matches("mailbox|ingress|delivery")) throw new IOException("Unknown service role");
        Properties build = new Properties();
        try (var stream = FoundationSettings.class.getResourceAsStream("/foundation-source.properties")) {
            if (stream == null) throw new IOException("Missing source identity"); build.load(stream);
        }
        if (!role.equals(build.getProperty("service"))) throw new IOException("Build role mismatch");
        return new FoundationSettings(role,build.getProperty("source.sha"),Path.of(required("GUIHONG_WITNESS_ROOT")),
                required("GUIHONG_INTERNAL_TOKEN"),required("GUIHONG_S3_ENDPOINT"),required("GUIHONG_S3_BUCKET"),
                required("GUIHONG_S3_KEY"),required("GUIHONG_S3_SECRET"),required("GUIHONG_NAMESRV"),required("GUIHONG_BROKER"));
    }
    private static String required(String key) {
        String value=System.getenv(key);
        if (value==null || value.isBlank()) throw new IllegalStateException("Missing required setting "+key);
        return value;
    }
    // Never inherit record's default rendering of secret fields into logs/errors.
    public String toString() { return "FoundationSettings[role="+role+",source="+sourceSha+"]"; }
}
