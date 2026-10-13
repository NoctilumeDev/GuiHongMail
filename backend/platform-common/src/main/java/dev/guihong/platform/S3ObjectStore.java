package dev.guihong.platform;

import java.io.IOException;
import java.net.URI;
import java.time.Duration;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.core.checksums.RequestChecksumCalculation;
import software.amazon.awssdk.core.checksums.ResponseChecksumValidation;
import software.amazon.awssdk.core.retry.RetryPolicy;
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.DeleteObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.HeadBucketRequest;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

public final class S3ObjectStore implements ObjectStore {
    public static final int MAX_BYTES = 5 * 1024 * 1024;
    private final S3Client client;
    private final String bucket;
    public S3ObjectStore(String endpoint, String bucket, String key, String secret) {
        URI uri = URI.create(endpoint);
        if (!uri.getHost().equals("127.0.0.1") || !uri.getScheme().equals("http")) throw new IllegalArgumentException("Approved profile requires loopback S3");
        this.bucket = bucket;
        client = S3Client.builder().endpointOverride(uri).region(Region.US_EAST_1).forcePathStyle(true)
                .requestChecksumCalculation(RequestChecksumCalculation.WHEN_REQUIRED)
                .responseChecksumValidation(ResponseChecksumValidation.WHEN_REQUIRED)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create(key, secret)))
                .httpClientBuilder(UrlConnectionHttpClient.builder().connectionTimeout(Duration.ofSeconds(3)).socketTimeout(Duration.ofSeconds(10)))
                .overrideConfiguration(c -> c.apiCallTimeout(Duration.ofSeconds(10)).apiCallAttemptTimeout(Duration.ofSeconds(8)).retryPolicy(RetryPolicy.none()))
                .build();
    }
    private void key(String key) {
        if (key == null || !key.matches("[a-zA-Z0-9][a-zA-Z0-9/_-]{0,180}")) throw new IllegalArgumentException("Invalid object coordinate");
    }
    public void put(String key, byte[] data) {
        key(key);
        if (data.length > MAX_BYTES) throw new IllegalArgumentException("Message size limit exceeded");
        client.putObject(PutObjectRequest.builder().bucket(bucket).key(key).build(), RequestBody.fromBytes(data));
    }
    public byte[] get(String key) {
        key(key);
        try (var stream = client.getObject(GetObjectRequest.builder().bucket(bucket).key(key).build())) {
            if (stream.response().contentLength() > MAX_BYTES) throw new IllegalStateException("Stored object exceeds limit");
            byte[] data = stream.readNBytes(MAX_BYTES + 1);
            if (data.length > MAX_BYTES) throw new IllegalStateException("Stored object exceeds limit");
            return data;
        } catch (IOException error) { throw new IllegalStateException("Storage unavailable", error); }
    }
    public void delete(String key) { key(key); client.deleteObject(DeleteObjectRequest.builder().bucket(bucket).key(key).build()); }
    public boolean ready() {
        try { client.headBucket(HeadBucketRequest.builder().bucket(bucket).build()); return true; }
        catch (RuntimeException error) { return false; }
    }
    public void close() { client.close(); }
}
