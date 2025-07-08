pipeline {
    agent any
    environment {
        IMAGE_NAME = "suchokrates1/retrievershop-suite"
        TAG = "latest"
    }
    stages {
        stage('Build Docker image') {
            steps {
                script {
                    docker.build("${IMAGE_NAME}:${TAG}", "-f magazyn/Dockerfile magazyn")
                }
            }
        }
        // stage('Push to Docker Hub') {
        //     steps {
        //         withDockerRegistry([ credentialsId: 'dockerhub', url: '' ]) {
        //             docker.image("${IMAGE_NAME}:${TAG}").push()
        //         }
        //     }
        // }
    }
}
